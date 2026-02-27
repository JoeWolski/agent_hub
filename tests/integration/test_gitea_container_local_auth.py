from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import agent_hub.server as hub_server


GITEA_IMAGE = "gitea/gitea:1.22.6"


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )


def _assert_ok(result: subprocess.CompletedProcess[str], *, context: str) -> None:
    if result.returncode == 0:
        return
    raise AssertionError(
        f"{context} failed with exit code {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _wait_http_ok(url: str, *, timeout_sec: float = 120.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2.0) as response:
                if int(response.status or 0) == 200:
                    return
        except Exception:
            pass
        time.sleep(1.0)
    raise AssertionError(f"Timed out waiting for HTTP 200: {url}")


def _api_json(
    method: str,
    url: str,
    *,
    token: str = "",
    basic_user: str = "",
    basic_password: str = "",
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"token {token}"
    request = Request(url, method=method, headers=headers, data=body)
    if basic_user:
        auth = f"{basic_user}:{basic_password}".encode("utf-8")
        import base64

        request.add_header("Authorization", "Basic " + base64.b64encode(auth).decode("ascii"))
    try:
        with urlopen(request, timeout=20.0) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
            payload_obj = json.loads(raw) if raw else {}
            if not isinstance(payload_obj, dict):
                payload_obj = {"value": payload_obj}
            return int(response.status), payload_obj
    except Exception as exc:
        import urllib.error

        if isinstance(exc, urllib.error.HTTPError):
            raw = exc.read().decode("utf-8", errors="replace").strip()
            payload_obj = json.loads(raw) if raw else {}
            if not isinstance(payload_obj, dict):
                payload_obj = {"value": payload_obj}
            return int(exc.code), payload_obj
        raise


@dataclass
class _GiteaContainer:
    name: str
    base_url: str


def _ensure_local_image_available() -> bool:
    probe = _run(["docker", "image", "inspect", GITEA_IMAGE])
    return probe.returncode == 0


def _start_gitea_container(tmp_dir: Path) -> _GiteaContainer:
    port = _free_port()
    name = f"agent-hub-gitea-int-{int(time.time())}-{port}"
    base_url = f"http://host.docker.internal:{port}"
    data_dir = tmp_dir / "gitea-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    start = _run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            "USER_UID=1000",
            "-e",
            "USER_GID=1000",
            "-e",
            "GITEA__security__INSTALL_LOCK=true",
            "-e",
            "GITEA__service__DISABLE_REGISTRATION=true",
            "-e",
            f"GITEA__server__ROOT_URL={base_url}/",
            "-p",
            f"{port}:3000",
            "-v",
            f"{data_dir}:/data",
            GITEA_IMAGE,
        ]
    )
    _assert_ok(start, context="docker run gitea")
    _wait_http_ok(f"{base_url}/api/v1/version")
    return _GiteaContainer(name=name, base_url=base_url)


def _stop_gitea_container(container: _GiteaContainer) -> None:
    _run(["docker", "rm", "-f", container.name])


def _create_user(container: _GiteaContainer, username: str, password: str, email: str) -> None:
    create = _run(
        [
            "docker",
            "exec",
            "--user",
            "git",
            container.name,
            "gitea",
            "admin",
            "user",
            "create",
            "--username",
            username,
            "--password",
            password,
            "--email",
            email,
            "--admin",
            "--must-change-password=false",
        ]
    )
    _assert_ok(create, context=f"create gitea user {username}")


def _create_token(container: _GiteaContainer, username: str, password: str, token_name: str) -> str:
    status, payload = _api_json(
        "POST",
        f"{container.base_url}/api/v1/users/{username}/tokens",
        basic_user=username,
        basic_password=password,
        payload={"name": token_name, "scopes": ["all"]},
    )
    if status != 201:
        raise AssertionError(f"create token failed for {username}: status={status} payload={payload}")
    token = str(payload.get("sha1") or "").strip()
    if not token:
        raise AssertionError(f"token missing for {username}: {payload}")
    return token


def _create_repo(container: _GiteaContainer, token: str, repo_name: str) -> None:
    status, payload = _api_json(
        "POST",
        f"{container.base_url}/api/v1/user/repos",
        token=token,
        payload={"name": repo_name, "private": False},
    )
    if status != 201:
        raise AssertionError(f"create repo failed: status={status} payload={payload}")


def test_local_gitea_container_multi_repo_multi_key_git_and_gh_without_agent_tools(
    integration_tmp_dir: Path,
    docker_daemon_available: bool,
) -> None:
    if not docker_daemon_available:
        pytest.skip("docker daemon is unavailable")
    if shutil.which("gh") is None:
        pytest.skip("gh CLI is unavailable")
    # Keep this integration deterministic and offline; do not pull during test execution.
    if not _ensure_local_image_available():
        pytest.skip(f"required local image is not available: {GITEA_IMAGE}")

    gitea = _start_gitea_container(integration_tmp_dir)
    try:
        # Provision two identities, two tokens, and two repos in a real local forge container.
        creds = []
        for idx in (1, 2):
            username = f"local-user-{idx}"
            password = f"local-pass-{idx}-12345"
            email = f"local-user-{idx}@example.com"
            repo_name = f"repo-{idx}"
            _create_user(gitea, username, password, email)
            token = _create_token(gitea, username, password, f"token-{idx}")
            _create_repo(gitea, token, repo_name)
            creds.append((username, token, repo_name))

        # Validate first-attempt git + gh commands for each key/repo without any agent_tools flow.
        for idx, (username, token, repo_name) in enumerate(creds, start=1):
            repo_url = f"{gitea.base_url}/{username}/{repo_name}.git"
            parsed = urlsplit(repo_url)
            remote_auth_url = f"{parsed.scheme}://{username}:{token}@{parsed.netloc}{parsed.path}"

            env = os.environ.copy()
            env["GH_TOKEN"] = token
            env["GITHUB_TOKEN"] = token
            env["XDG_CONFIG_HOME"] = str(integration_tmp_dir / f"gh-config-{idx}")
            Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)

            gh_token = _run(["gh", "auth", "token"], env=env)
            _assert_ok(gh_token, context=f"gh auth token repo-{idx}")
            assert gh_token.stdout.strip() == token

            gh_setup = _run(["gh", "auth", "setup-git"], env=env)
            _assert_ok(gh_setup, context=f"gh auth setup-git repo-{idx}")

            seed_dir = integration_tmp_dir / f"seed-{idx}"
            seed_dir.mkdir(parents=True, exist_ok=True)
            _assert_ok(_run(["git", "init"], cwd=seed_dir, env=env), context=f"git init seed-{idx}")
            readme = seed_dir / "README.md"
            readme.write_text(f"seed {idx}\n", encoding="utf-8")
            _assert_ok(_run(["git", "add", "README.md"], cwd=seed_dir, env=env), context=f"git add seed-{idx}")
            _assert_ok(
                _run(
                    [
                        "git",
                        "-c",
                        "user.name=Agent Integration",
                        "-c",
                        "user.email=agent.integration@example.com",
                        "commit",
                        "-m",
                        f"seed repo {idx}",
                    ],
                    cwd=seed_dir,
                    env=env,
                ),
                context=f"git commit seed-{idx}",
            )
            _assert_ok(_run(["git", "remote", "add", "origin", remote_auth_url], cwd=seed_dir, env=env), context=f"git remote add seed-{idx}")
            _assert_ok(_run(["git", "push", "origin", "HEAD:master"], cwd=seed_dir, env=env), context=f"git push seed-{idx}")

            clone_dir = integration_tmp_dir / f"clone-{idx}"
            clone = _run(["git", "clone", remote_auth_url, str(clone_dir)], env=env)
            _assert_ok(clone, context=f"git clone repo-{idx}")
            _assert_ok(_run(["git", "fetch", "origin"], cwd=clone_dir, env=env), context=f"git fetch repo-{idx}")
            _assert_ok(_run(["git", "pull", "--ff-only", "origin", "master"], cwd=clone_dir, env=env), context=f"git pull repo-{idx}")
    finally:
        _stop_gitea_container(gitea)
