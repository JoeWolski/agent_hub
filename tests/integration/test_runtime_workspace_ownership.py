from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SETUP_IMAGE = "agent-ubuntu2204-setup:runtime-ownership-test"


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        text=True,
        capture_output=True,
    )


def _docker_available() -> bool:
    probe = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    return probe.returncode == 0 and bool(probe.stdout.strip())


def _daemon_visible_workspace_tmp_root() -> tuple[Path, Path]:
    container_tmp_root = Path("/workspace/tmp")
    container_id = socket.gethostname().strip()
    if not container_id:
        return container_tmp_root, container_tmp_root
    inspect = _run(
        [
            "docker",
            "inspect",
            container_id,
            "--format",
            "{{range .Mounts}}{{if eq .Destination \"/workspace/tmp\"}}{{.Source}}{{end}}{{end}}",
        ]
    )
    source = str(inspect.stdout or "").strip()
    if inspect.returncode == 0 and source:
        return Path(source), container_tmp_root
    return container_tmp_root, container_tmp_root


def _ensure_setup_image() -> None:
    build_base = _run(
        [
            "docker",
            "build",
            "-f",
            str(ROOT / "docker/agent_cli/Dockerfile.base"),
            "-t",
            "agent-cli-base:latest",
            str(ROOT),
        ]
    )
    assert build_base.returncode == 0, build_base.stderr or build_base.stdout

    build_runtime = _run(
        [
            "docker",
            "build",
            "-f",
            str(ROOT / "docker/agent_cli/Dockerfile"),
            "--build-arg",
            "BASE_IMAGE=agent-cli-base:latest",
            "--build-arg",
            "AGENT_PROVIDER=none",
            "-t",
            SETUP_IMAGE,
            str(ROOT),
        ]
    )
    assert build_runtime.returncode == 0, build_runtime.stderr or build_runtime.stdout


def test_runtime_workspace_and_project_paths_owned_by_spoofed_identity() -> None:
    if not _docker_available():
        pytest.skip("docker daemon is unavailable")

    _ensure_setup_image()

    spoof_uid = os.getuid() + 20000
    spoof_gid = os.getgid() + 20000

    daemon_tmp_root, container_tmp_root = _daemon_visible_workspace_tmp_root()
    relative_project = Path("agent-hub-int-runtime-ownership/project")
    host_project = daemon_tmp_root / relative_project
    container_project_source = container_tmp_root / relative_project
    container_project_target = Path("/workspace/runtime-ownership-project")

    container_project_source.mkdir(parents=True, exist_ok=True)
    ownership_setup = _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{host_project}:/target",
            "alpine:3.20",
            "sh",
            "-lc",
            f"chown -R {spoof_uid}:{spoof_gid} /target",
        ]
    )
    assert ownership_setup.returncode == 0, ownership_setup.stderr or ownership_setup.stdout

    probe_cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--tmpfs",
        "/tmp:mode=1777,exec",
        "--init",
        "--user",
        "0:0",
        "--gpus",
        "all",
        "--workdir",
        str(container_project_target),
        "--env",
        "HOME=/workspace",
        "--env",
        "CONTAINER_HOME=/workspace",
        "--env",
        f"CONTAINER_PROJECT_PATH={container_project_target}",
        "--env",
        f"LOCAL_UID={spoof_uid}",
        "--env",
        f"LOCAL_GID={spoof_gid}",
        "--volume",
        f"{host_project}:{container_project_target}",
        SETUP_IMAGE,
        "bash",
        "-lc",
        (
            "stat -c '%u:%g /workspace' /workspace; "
            f"stat -c '%u:%g {container_project_target}' {container_project_target}"
        ),
    ]
    probe = _run(probe_cmd)
    assert probe.returncode == 0, probe.stderr or probe.stdout

    lines = [line.strip() for line in (probe.stdout or "").splitlines() if line.strip()]
    assert lines, probe.stdout
    expected_workspace = f"{spoof_uid}:{spoof_gid} /workspace"
    expected_project = f"{spoof_uid}:{spoof_gid} {container_project_target}"
    assert expected_workspace in lines, probe.stdout
    assert expected_project in lines, probe.stdout
