from __future__ import annotations

import fcntl
import queue
import struct
import termios


def queue_put_drop_oldest(listener: queue.Queue[str | None], value: str | None) -> None:
    try:
        listener.put_nowait(value)
        return
    except queue.Full:
        pass

    try:
        listener.get_nowait()
    except queue.Empty:
        return

    try:
        listener.put_nowait(value)
    except queue.Full:
        return


def set_terminal_size(fd: int, cols: int, rows: int) -> None:
    safe_cols = max(1, int(cols))
    safe_rows = max(1, int(rows))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", safe_rows, safe_cols, 0, 0))

