from __future__ import annotations

import codecs
import os
import queue
import subprocess
from threading import Lock, Thread
from typing import Any, Callable

from fastapi import HTTPException
from agent_hub.runtime import queue_put_drop_oldest, set_terminal_size


class RuntimeDomain:
    def __init__(
        self,
        *,
        runtime_factory: Callable[..., Any],
        is_process_running: Callable[[int | None], bool],
        signal_process_group_winch: Callable[[int], None],
        chat_log_path: Callable[[str], Any],
        on_runtime_exit: Callable[[str, int | None], None],
        collect_submitted_prompts: Callable[[str, str], list[str]],
        record_submitted_prompt: Callable[[str, Any], bool],
        terminal_queue_max: int,
        default_cols: int,
        default_rows: int,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._is_process_running = is_process_running
        self._signal_process_group_winch = signal_process_group_winch
        self._chat_log_path = chat_log_path
        self._on_runtime_exit = on_runtime_exit
        self._collect_submitted_prompts = collect_submitted_prompts
        self._record_submitted_prompt = record_submitted_prompt
        self._terminal_queue_max = int(terminal_queue_max)
        self._default_cols = int(default_cols)
        self._default_rows = int(default_rows)
        self._runtime_lock = Lock()
        self._chat_runtimes: dict[str, Any] = {}

    @staticmethod
    def queue_put(listener: queue.Queue[str | None], value: str | None) -> None:
        queue_put_drop_oldest(listener, value)

    def runtime_ids(self) -> list[str]:
        with self._runtime_lock:
            return list(self._chat_runtimes.keys())

    def _pop_runtime(self, chat_id: str) -> Any | None:
        with self._runtime_lock:
            return self._chat_runtimes.pop(chat_id, None)

    def close_runtime(self, chat_id: str) -> None:
        runtime = self._pop_runtime(chat_id)
        if runtime is None:
            return
        listeners = list(runtime.listeners)
        runtime.listeners.clear()
        try:
            os.close(runtime.master_fd)
        except OSError:
            pass
        for listener in listeners:
            self.queue_put(listener, None)

    def _runtime_for_chat(self, chat_id: str) -> Any | None:
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
        if runtime is None:
            return None
        if self._is_process_running(runtime.process.pid):
            return runtime
        self.close_runtime(chat_id)
        return None

    def _broadcast_runtime_output(self, chat_id: str, text: str) -> None:
        if not text:
            return
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
            listeners = list(runtime.listeners) if runtime else []
        for listener in listeners:
            self.queue_put(listener, text)

    def _runtime_reader_loop(self, chat_id: str, master_fd: int, log_path: Any) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("ab") as log_file:
                while True:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    log_file.write(chunk)
                    log_file.flush()
                    decoded = decoder.decode(chunk)
                    if decoded:
                        self._broadcast_runtime_output(chat_id, decoded)
                tail = decoder.decode(b"", final=True)
                if tail:
                    self._broadcast_runtime_output(chat_id, tail)
        finally:
            runtime = self._pop_runtime(chat_id)
            listeners = list(runtime.listeners) if runtime else []
            exit_code: int | None = None
            if runtime:
                polled_exit_code = runtime.process.poll()
                if isinstance(polled_exit_code, int):
                    exit_code = polled_exit_code
                runtime.listeners.clear()
            try:
                os.close(master_fd)
            except OSError:
                pass
            for listener in listeners:
                self.queue_put(listener, None)
            if runtime is not None:
                self._on_runtime_exit(chat_id, exit_code)

    @staticmethod
    def _set_terminal_size(fd: int, cols: int, rows: int) -> None:
        set_terminal_size(fd, cols, rows)

    def _register_runtime(self, chat_id: str, process: subprocess.Popen[Any], master_fd: int) -> None:
        previous = self._pop_runtime(chat_id)
        if previous is not None:
            try:
                os.close(previous.master_fd)
            except OSError:
                pass
            for listener in list(previous.listeners):
                self.queue_put(listener, None)

        with self._runtime_lock:
            self._chat_runtimes[chat_id] = self._runtime_factory(process=process, master_fd=master_fd)

        reader_thread = Thread(
            target=self._runtime_reader_loop,
            args=(chat_id, master_fd, self._chat_log_path(chat_id)),
            daemon=True,
        )
        reader_thread.start()

    def spawn_chat_process(self, chat_id: str, cmd: list[str]) -> subprocess.Popen[Any]:
        master_fd, slave_fd = os.openpty()
        try:
            self._set_terminal_size(slave_fd, self._default_cols, self._default_rows)
            proc = subprocess.Popen(
                cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        except Exception:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                os.close(slave_fd)
            except OSError:
                pass
            raise

        try:
            os.close(slave_fd)
        except OSError:
            pass

        self._register_runtime(chat_id, proc, master_fd)
        return proc

    def _chat_log_history(self, chat_id: str) -> str:
        log_path = self._chat_log_path(chat_id)
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="ignore")

    def attach_terminal(self, chat_id: str) -> tuple[queue.Queue[str | None], str]:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        listener: queue.Queue[str | None] = queue.Queue(maxsize=self._terminal_queue_max)
        with self._runtime_lock:
            active_runtime = self._chat_runtimes.get(chat_id)
            if active_runtime is None:
                raise HTTPException(status_code=409, detail="Chat is not running.")
            active_runtime.listeners.add(listener)
        return listener, self._chat_log_history(chat_id)

    def detach_terminal(self, chat_id: str, listener: queue.Queue[str | None]) -> None:
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
            if runtime is None:
                return
            runtime.listeners.discard(listener)

    def write_terminal_input(self, chat_id: str, data: str) -> None:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        if not data:
            return
        try:
            os.write(runtime.master_fd, data.encode("utf-8", errors="ignore"))
        except OSError as exc:
            raise HTTPException(status_code=409, detail="Failed to write to chat terminal.") from exc
        submissions = self._collect_submitted_prompts(chat_id, data)
        for prompt in submissions:
            self._record_submitted_prompt(chat_id, prompt)

    def resize_terminal(self, chat_id: str, cols: int, rows: int) -> None:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        try:
            self._set_terminal_size(runtime.master_fd, cols, rows)
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid terminal resize request.") from exc
        self._signal_process_group_winch(int(runtime.process.pid))
