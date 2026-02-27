from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "tools" / "testing" / "preflight_integration_env.py"


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("preflight_integration_env", PREFLIGHT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mount_probe_roots_use_agent_hub_tmp_host_hint_for_hub_chat_happy_path(monkeypatch, tmp_path: Path) -> None:
    module = _load_preflight_module()
    override_root = tmp_path / "override-root"
    host_hint_root = tmp_path / "host-hint-root"
    workspace_tmp_root = tmp_path / "workspace-tmp"
    default_tmp_root = tmp_path / "default-tmp"
    repo_tmp_root = tmp_path / "repo-tmp"

    monkeypatch.setattr(module, "TMP_ROOT", default_tmp_root)
    monkeypatch.setattr(module, "LOCAL_REPO_TMP_ROOT", repo_tmp_root)
    monkeypatch.setattr(module, "WORKSPACE_TMP_DIR", workspace_tmp_root)
    monkeypatch.setenv(module.DAEMON_VISIBLE_DIR_ENV, str(override_root))
    monkeypatch.setenv(module.AGENT_HUB_TMP_HOST_PATH_ENV, str(host_hint_root))

    roots = module._mount_probe_roots()
    assert roots
    assert roots[0].host_root == override_root
    assert roots[0].write_root == override_root
    assert roots[0].source == f"env:{module.DAEMON_VISIBLE_DIR_ENV}"

    hinted = next(
        (entry for entry in roots if entry.source == f"env:{module.AGENT_HUB_TMP_HOST_PATH_ENV}"),
        None,
    )
    assert hinted is not None
    assert hinted.host_root == host_hint_root
    assert hinted.write_root == workspace_tmp_root


def test_mount_probe_roots_are_deduplicated_by_host_and_write_roots(monkeypatch, tmp_path: Path) -> None:
    module = _load_preflight_module()
    shared_root = tmp_path / "shared"

    monkeypatch.setattr(module, "TMP_ROOT", shared_root)
    monkeypatch.setattr(module, "LOCAL_REPO_TMP_ROOT", shared_root)
    monkeypatch.setattr(module, "WORKSPACE_TMP_DIR", shared_root)
    monkeypatch.setenv(module.DAEMON_VISIBLE_DIR_ENV, str(shared_root))
    monkeypatch.delenv(module.AGENT_HUB_TMP_HOST_PATH_ENV, raising=False)

    roots = module._mount_probe_roots()
    pairs = {(str(entry.host_root), str(entry.write_root)) for entry in roots}
    assert len(roots) == len(pairs)
