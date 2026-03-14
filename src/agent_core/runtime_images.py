from __future__ import annotations

import fcntl
import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any


def short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def snapshot_setup_runtime_image_for_snapshot(
    snapshot_tag: str,
    *,
    error_factory: Callable[[str], Exception],
) -> str:
    normalized_snapshot_tag = str(snapshot_tag or "").strip()
    if not normalized_snapshot_tag:
        raise error_factory("Snapshot tag is required to resolve setup runtime image.")
    return f"agent-runtime-setup-{short_hash(normalized_snapshot_tag)}"


def runtime_image_build_lock_path(target_image: str, *, lock_dir: Path) -> Path:
    digest = hashlib.sha256(str(target_image or "").encode("utf-8")).hexdigest()
    return lock_dir / f"{digest}.lock"


@contextmanager
def runtime_image_build_lock(
    target_image: str,
    *,
    lock_dir: Path | None,
    error_factory: Callable[[str], Exception],
) -> Iterator[None]:
    if lock_dir is None:
        with nullcontext():
            yield
        return

    lock_path = runtime_image_build_lock_path(target_image, lock_dir=lock_dir)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("a+", encoding="utf-8")
    except OSError as exc:
        raise error_factory(
            f"Failed to initialize runtime image build lock for '{target_image}' at {lock_path}: {exc}"
        ) from exc

    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise error_factory(
                f"Failed to acquire runtime image build lock for '{target_image}' at {lock_path}: {exc}"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_handle.close()


def build_runtime_image(
    *,
    repo_root: Path,
    dockerfile: str,
    base_image: str,
    target_image: str,
    agent_provider: str,
    run_command: Callable[..., Any],
) -> None:
    run_command(
        [
            "docker",
            "build",
            "-f",
            str(repo_root / dockerfile),
            "--build-arg",
            f"BASE_IMAGE={base_image}",
            "--build-arg",
            f"AGENT_PROVIDER={agent_provider}",
            "-t",
            target_image,
            str(repo_root),
        ],
        cwd=repo_root,
    )


def build_agent_cli_base_image(
    *,
    repo_root: Path,
    base_dockerfile: str,
    base_image: str,
    run_command: Callable[..., Any],
) -> None:
    run_command(
        [
            "docker",
            "build",
            "-f",
            str(repo_root / base_dockerfile),
            "-t",
            base_image,
            str(repo_root),
        ],
        cwd=repo_root,
    )


def ensure_runtime_image_built_if_missing(
    *,
    base_image: str,
    target_image: str,
    agent_provider: str,
    repo_root: Path,
    runtime_dockerfile: str,
    base_dockerfile: str,
    agent_cli_base_image: str,
    docker_image_exists: Callable[[str], bool],
    run_command: Callable[..., Any],
    lock_dir: Path | None,
    lock_error_factory: Callable[[str], Exception],
    on_build_base_image: Callable[[str, str], None] | None = None,
    on_build_runtime_image: Callable[[str, str, str, str], None] | None = None,
) -> None:
    if base_image == agent_cli_base_image:
        with runtime_image_build_lock(agent_cli_base_image, lock_dir=lock_dir, error_factory=lock_error_factory):
            if on_build_base_image is not None:
                on_build_base_image(agent_cli_base_image, base_dockerfile)
            build_agent_cli_base_image(
                repo_root=repo_root,
                base_dockerfile=base_dockerfile,
                base_image=agent_cli_base_image,
                run_command=run_command,
            )

    if docker_image_exists(target_image):
        return

    with runtime_image_build_lock(target_image, lock_dir=lock_dir, error_factory=lock_error_factory):
        if docker_image_exists(target_image):
            return
        if on_build_runtime_image is not None:
            on_build_runtime_image(target_image, runtime_dockerfile, base_image, agent_provider)
        build_runtime_image(
            repo_root=repo_root,
            dockerfile=runtime_dockerfile,
            base_image=base_image,
            target_image=target_image,
            agent_provider=agent_provider,
            run_command=run_command,
        )


def read_openai_api_key(
    path: Path,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    ignore_read_errors: bool = False,
) -> str | None:
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding=encoding, errors=errors)
    except (OSError, UnicodeError):
        if ignore_read_errors:
            return None
        raise

    for line in text.splitlines():
        match = re.match(r"^\s*OPENAI_API_KEY\s*=\s*(.+?)\s*$", line)
        if not match:
            continue
        value = match.group(1).strip().strip('"').strip("'")
        if value:
            return value
    return None
