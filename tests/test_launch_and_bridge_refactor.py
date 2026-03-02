from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_cli import cli as image_cli
from agent_core import launch as core_launch
from agent_core import load_agent_runtime_config


class _PopTrackingDict(dict[str, object]):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.pop_called = False

    def pop(self, key: object, default: object = None) -> object:
        self.pop_called = True
        return super().pop(key, default)


class LaunchAndBridgeRefactorTests(unittest.TestCase):
    def test_compile_agent_cli_command_honors_bootstrap_and_alt_screen_flags(self) -> None:
        base_spec = core_launch.LaunchSpec(
            repo_root=Path("/repo"),
            workspace=Path("/repo/workspace"),
            container_project_name="workspace",
            agent_home_path=Path("/repo/.agent-home"),
            runtime_config_file=Path("/repo/config.toml"),
            system_prompt_file=Path("/repo/SYSTEM_PROMPT.md"),
            agent_command="codex",
            run_mode="docker",
            local_uid=1000,
            local_gid=1000,
            local_user="agent",
        )

        default_cmd = core_launch.compile_agent_cli_command(base_spec)
        self.assertIn("--bootstrap-as-root", default_cmd)
        self.assertIn("--no-alt-screen", default_cmd)

        explicit_false_cmd = core_launch.compile_agent_cli_command(
            core_launch.LaunchSpec(
                repo_root=base_spec.repo_root,
                workspace=base_spec.workspace,
                container_project_name=base_spec.container_project_name,
                agent_home_path=base_spec.agent_home_path,
                runtime_config_file=base_spec.runtime_config_file,
                system_prompt_file=base_spec.system_prompt_file,
                agent_command=base_spec.agent_command,
                run_mode=base_spec.run_mode,
                local_uid=base_spec.local_uid,
                local_gid=base_spec.local_gid,
                local_user=base_spec.local_user,
                bootstrap_as_root=False,
                no_alt_screen=False,
            )
        )
        self.assertNotIn("--bootstrap-as-root", explicit_false_cmd)
        self.assertNotIn("--no-alt-screen", explicit_false_cmd)

    def test_public_cli_option_values_helper_and_parser_usage(self) -> None:
        values = core_launch.cli_option_values(
            [
                "--env-var",
                "A=1",
                "--env-var=B=2",
                "-e",
                "C=3",
                "-e=D=4",
                "--",
                "--env-var",
                "IGNORED=1",
            ],
            long_option="--env-var",
            short_option="-e",
        )
        self.assertEqual(values, ["A=1", "B=2", "C=3", "D=4"])

        with patch.object(core_launch, "cli_option_values") as helper:
            helper.side_effect = [
                ["ro-value"],
                ["rw-value"],
                ["env-value"],
            ]
            parsed = core_launch.parse_compiled_agent_cli_command(["agent_cli", "--"])

        self.assertEqual(parsed.ro_mounts, ("ro-value",))
        self.assertEqual(parsed.rw_mounts, ("rw-value",))
        self.assertEqual(parsed.env_vars, ("env-value",))
        self.assertEqual(helper.call_count, 3)

    def test_runtime_bridge_close_prefers_canonical_state_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_config_path = Path(tmp) / "runtime.toml"
            runtime_config_path.write_text("[runtime]\n", encoding="utf-8")

            sessions = _PopTrackingDict({"session-1": {"token": "abc"}})

            class State:
                _agent_tools_sessions_lock = threading.Lock()
                _agent_tools_sessions = sessions

                def __init__(self) -> None:
                    self.removed_session_id = ""

                def _remove_agent_tools_session(self, session_id: str) -> None:
                    self.removed_session_id = session_id

            state = State()
            bridge = image_cli._AgentToolsRuntimeBridge(
                runtime_config_path=runtime_config_path,
                env_vars=[],
                state=state,
                session_id="session-1",
                server=None,
                thread=None,
                cleanup_runtime_config=True,
            )
            bridge.close()

            self.assertEqual(state.removed_session_id, "session-1")
            self.assertFalse(sessions.pop_called)
            self.assertFalse(runtime_config_path.exists())

    def test_runtime_bridge_close_falls_back_to_session_pop_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_config_path = Path(tmp) / "runtime.toml"
            runtime_config_path.write_text("[runtime]\n", encoding="utf-8")

            sessions = {"session-2": {"token": "xyz"}}

            class State:
                _agent_tools_sessions_lock = threading.Lock()
                _agent_tools_sessions = sessions

            bridge = image_cli._AgentToolsRuntimeBridge(
                runtime_config_path=runtime_config_path,
                env_vars=[],
                state=State(),
                session_id="session-2",
                server=None,
                thread=None,
                cleanup_runtime_config=False,
            )
            bridge.close()

            self.assertNotIn("session-2", sessions)
            self.assertTrue(runtime_config_path.exists())

    def test_start_runtime_bridge_passes_hub_state_reconcile_ctor_option_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "agent.config.toml"
            config_path.write_text(
                "[identity]\n\n[paths]\n\n[providers]\n\n[providers.defaults]\nmodel = 'test'\nmodel_provider = 'openai'\n\n[mcp]\n\n[auth]\n\n[logging]\n\n[runtime]\nrun_mode = 'docker'\n",
                encoding="utf-8",
            )
            runtime_config = load_agent_runtime_config(config_path)

            captured: dict[str, object] = {}

            class FakeHubState:
                def __init__(
                    self,
                    *,
                    data_dir: Path,
                    config_file: Path,
                    runtime_config: object,
                    system_prompt_file: Path,
                    artifact_publish_base_url: str,
                    reconcile_project_build_on_init: bool,
                ) -> None:
                    captured["data_dir"] = data_dir
                    captured["config_file"] = config_file
                    captured["runtime_config"] = runtime_config
                    captured["system_prompt_file"] = system_prompt_file
                    captured["artifact_publish_base_url"] = artifact_publish_base_url
                    captured["reconcile_project_build_on_init"] = reconcile_project_build_on_init

            with patch("agent_hub.server.HubState", FakeHubState), patch(
                "agent_cli.cli._resolved_agent_hub_data_dir",
                return_value=tmp_path / "hub-data",
            ), patch(
                "agent_cli.cli._resolve_existing_project_context",
                side_effect=RuntimeError("stop_after_hub_state_init"),
            ):
                with self.assertRaisesRegex(RuntimeError, "stop_after_hub_state_init"):
                    image_cli._start_agent_tools_runtime_bridge(
                        project_path=tmp_path / "project",
                        host_codex_dir=tmp_path / ".codex",
                        config_path=config_path,
                        system_prompt_path=tmp_path / "SYSTEM_PROMPT.md",
                        agent_tools_config_path=None,
                        parsed_env_vars=[],
                        agent_provider=image_cli.agent_providers.CodexProvider(),
                        container_home=image_cli.DEFAULT_CONTAINER_HOME,
                        runtime_config=runtime_config,
                        effective_run_mode="docker",
                    )

            self.assertEqual(captured["artifact_publish_base_url"], "http://127.0.0.1")
            self.assertIs(captured["runtime_config"], runtime_config)
            self.assertEqual(captured["reconcile_project_build_on_init"], False)


if __name__ == "__main__":
    unittest.main()
