from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentCliDockerfileTests(unittest.TestCase):
    def test_claude_install_uses_isolated_home_and_config(self) -> None:
        dockerfile = (ROOT / "docker" / "agent_cli" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("install_home=/tmp/claude-install-home", dockerfile)
        self.assertIn(
            'HOME="${install_home}" XDG_CONFIG_HOME="${install_home}/.config" bash /tmp/claude-install.sh',
            dockerfile,
        )
        self.assertIn('cp -L "${install_home}/.local/bin/claude" /usr/local/bin/claude', dockerfile)
        self.assertIn('rm -rf "${install_home}"', dockerfile)
