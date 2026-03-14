from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core import build_inputs


class BuildInputsTests(unittest.TestCase):
    def test_resolve_requested_run_mode_prefers_cli(self) -> None:
        result = build_inputs.resolve_requested_run_mode(
            cli_run_mode="docker",
            configured_run_mode="native",
            default_run_mode="docker",
        )
        self.assertEqual(result, "docker")

    def test_validate_run_mode_requirements_rejects_native(self) -> None:
        with self.assertRaisesRegex(ValueError, "dockerized execution"):
            build_inputs.validate_run_mode_requirements(
                run_mode="native",
                docker_mode="docker",
                native_mode="native",
                run_mode_choices=("auto", "docker", "native"),
                docker_available=True,
                error_factory=lambda message: ValueError(message),
            )

    def test_validate_base_image_source_flags_rejects_mixed_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "--base cannot be combined"):
            build_inputs.validate_base_image_source_flags(
                base_docker_path="docker",
                base_docker_context="ctx",
                base_dockerfile=None,
                base_image="",
                base_image_tag=None,
                default_base_image="agent-base",
                error_factory=lambda message: ValueError(message),
            )

    def test_resolve_base_image_returns_tag_for_valid_base_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project_dir = tmp_path / "project"
            project_dir.mkdir()
            base_dir = tmp_path / "base"
            base_dir.mkdir()
            dockerfile = base_dir / "Dockerfile"
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")

            tag, context, resolved_dockerfile = build_inputs.resolve_base_image(
                base_docker_path=str(base_dir),
                base_docker_context=None,
                base_dockerfile=None,
                project_dir=project_dir,
                cwd=tmp_path,
                to_absolute=lambda value, cwd: (cwd / value).resolve(),
                sanitize_tag_component=lambda value: value.lower(),
                short_hash=lambda value: "abc123",
                error_factory=lambda message: ValueError(message),
            )

            self.assertEqual(tag, "agent-base-project-base-abc123")
            self.assertEqual(context, base_dir)
            self.assertEqual(resolved_dockerfile, dockerfile)


if __name__ == "__main__":
    unittest.main()
