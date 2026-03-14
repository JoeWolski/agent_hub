from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core import runtime_images


class RuntimeImagesTests(unittest.TestCase):
    def test_snapshot_setup_runtime_image_for_snapshot_requires_tag(self) -> None:
        with self.assertRaisesRegex(ValueError, "Snapshot tag is required"):
            runtime_images.snapshot_setup_runtime_image_for_snapshot(
                " ",
                error_factory=lambda message: ValueError(message),
            )

    def test_snapshot_setup_runtime_image_for_snapshot_is_stable(self) -> None:
        first = runtime_images.snapshot_setup_runtime_image_for_snapshot(
            "snapshot:alpha",
            error_factory=lambda message: ValueError(message),
        )
        second = runtime_images.snapshot_setup_runtime_image_for_snapshot(
            "snapshot:beta",
            error_factory=lambda message: ValueError(message),
        )
        self.assertTrue(first.startswith("agent-runtime-setup-"))
        self.assertTrue(second.startswith("agent-runtime-setup-"))
        self.assertNotEqual(first, second)

    def test_ensure_runtime_image_built_if_missing_with_lock_builds_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_dir = Path(tmp) / "locks"
            repo_root = Path(tmp)
            build_started = threading.Event()
            allow_finish = threading.Event()
            call_lock = threading.Lock()
            image_ready = {"value": False}
            build_calls: list[str] = []

            def docker_image_exists(tag: str) -> bool:
                self.assertEqual(tag, "agent-runtime-claude-test")
                with call_lock:
                    return bool(image_ready["value"])

            def run_command(cmd: list[str], cwd: Path | None = None) -> None:
                del cwd
                if cmd[:3] == ["docker", "build", "-f"] and "Dockerfile.base" not in cmd[3]:
                    with call_lock:
                        build_calls.append(cmd[-2])
                    build_started.set()
                    self.assertTrue(allow_finish.wait(timeout=2.0))
                    with call_lock:
                        image_ready["value"] = True

            def worker() -> None:
                runtime_images.ensure_runtime_image_built_if_missing(
                    base_image="snapshot:test",
                    target_image="agent-runtime-claude-test",
                    agent_provider="claude",
                    repo_root=repo_root,
                    runtime_dockerfile="docker/agent_cli/Dockerfile",
                    base_dockerfile="docker/agent_cli/Dockerfile.base",
                    agent_cli_base_image="agent-cli-base",
                    docker_image_exists=docker_image_exists,
                    run_command=run_command,
                    lock_dir=lock_dir,
                    lock_error_factory=lambda message: RuntimeError(message),
                )

            first = threading.Thread(target=worker, daemon=True)
            second = threading.Thread(target=worker, daemon=True)
            first.start()
            self.assertTrue(build_started.wait(timeout=2.0))
            second.start()
            self.assertEqual(len(build_calls), 1)
            allow_finish.set()
            first.join(timeout=2.0)
            second.join(timeout=2.0)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(len(build_calls), 1)

    def test_read_openai_api_key_ignores_read_errors_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "openai.env"
            key_file.write_bytes(b"\xff\xfe\x00")
            key = runtime_images.read_openai_api_key(
                key_file,
                encoding="utf-8",
                errors="strict",
                ignore_read_errors=True,
            )
            self.assertIsNone(key)


if __name__ == "__main__":
    unittest.main()
