from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def resolve_requested_run_mode(
    *,
    cli_run_mode: str | None,
    configured_run_mode: str,
    default_run_mode: str,
) -> str:
    if cli_run_mode is not None:
        return str(cli_run_mode).strip().lower()
    configured = str(configured_run_mode or "").strip().lower()
    return configured or str(default_run_mode).strip().lower()


def resolve_effective_run_mode(
    requested_run_mode: str,
    *,
    auto_mode: str,
    docker_mode: str,
) -> str:
    if requested_run_mode == auto_mode:
        return docker_mode
    return requested_run_mode


def validate_run_mode_requirements(
    *,
    run_mode: str,
    docker_mode: str,
    native_mode: str,
    run_mode_choices: list[str] | tuple[str, ...],
    docker_available: bool,
    error_factory: Callable[[str], Exception],
) -> None:
    if run_mode == docker_mode:
        if not docker_available:
            raise error_factory("run_mode=docker requires docker in PATH.")
        return
    if run_mode == native_mode:
        raise error_factory("run_mode=native is configured but agent_cli only supports dockerized execution.")
    supported = ", ".join(run_mode_choices)
    raise error_factory(f"Invalid run mode '{run_mode}'. Supported values: {supported}.")


def resolve_base_image(
    *,
    base_docker_path: str | None,
    base_docker_context: str | None,
    base_dockerfile: str | None,
    project_dir: Path,
    cwd: Path,
    to_absolute: Callable[[str, Path], Path],
    sanitize_tag_component: Callable[[str], str],
    short_hash: Callable[[str], str],
    error_factory: Callable[[str], Exception],
    default_dockerfile_name: str = "Dockerfile",
) -> tuple[str, Path, Path] | tuple[None, None, None]:
    resolved_context: Path | None = None
    resolved_dockerfile: Path | None = None

    if base_docker_path:
        path = to_absolute(base_docker_path, cwd)
        if path.is_dir():
            resolved_context = path
            resolved_dockerfile = path / default_dockerfile_name
        elif path.is_file():
            resolved_dockerfile = path
            resolved_context = path.parent
        else:
            raise error_factory(
                f"Invalid --base path: {base_docker_path}. "
                f"Expected an existing Dockerfile path or a directory containing a {default_dockerfile_name}."
            )
    elif base_docker_context or base_dockerfile:
        if base_docker_context:
            resolved_context = to_absolute(base_docker_context, cwd)
            if not resolved_context.is_dir():
                raise error_factory(
                    f"Invalid --base-docker-context: {base_docker_context} (must be an existing directory)"
                )

        if base_dockerfile:
            if Path(base_dockerfile).is_absolute():
                resolved_dockerfile = to_absolute(base_dockerfile, cwd)
            elif resolved_context is not None:
                resolved_dockerfile = resolved_context / base_dockerfile
            else:
                raise error_factory("--base-docker-context is required when --base-dockerfile is relative")
        elif resolved_context is not None:
            resolved_dockerfile = resolved_context / default_dockerfile_name

    if resolved_dockerfile is None:
        return None, None, None

    if not resolved_dockerfile.is_file():
        raise error_factory(f"Base Dockerfile not found: {resolved_dockerfile}")

    if resolved_context is None:
        resolved_context = resolved_dockerfile.parent

    tag = (
        f"agent-base-{sanitize_tag_component(project_dir.name)}-"
        f"{sanitize_tag_component(resolved_context.name)}-"
        f"{short_hash(str(resolved_dockerfile))}"
    )
    return tag, resolved_context, resolved_dockerfile


def validate_base_image_source_flags(
    *,
    base_docker_path: str | None,
    base_docker_context: str | None,
    base_dockerfile: str | None,
    base_image: str,
    base_image_tag: str | None,
    default_base_image: str,
    error_factory: Callable[[str], Exception],
) -> None:
    has_base_path = bool(str(base_docker_path or "").strip())
    has_base_context = bool(str(base_docker_context or "").strip())
    has_base_dockerfile = bool(str(base_dockerfile or "").strip())
    has_docker_source = has_base_path or has_base_context or has_base_dockerfile
    normalized_base_image = str(base_image or "").strip()

    if has_base_path and (has_base_context or has_base_dockerfile):
        raise error_factory("--base cannot be combined with --base-docker-context or --base-dockerfile.")

    if has_docker_source and normalized_base_image and normalized_base_image != default_base_image:
        raise error_factory("--base-image cannot be combined with --base/--base-docker-context/--base-dockerfile.")

    if base_image_tag and not has_docker_source:
        raise error_factory("--base-image-tag requires --base, --base-docker-context, or --base-dockerfile.")
