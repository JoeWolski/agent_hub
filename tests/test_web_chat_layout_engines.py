from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebChatLayoutEngineTests(unittest.TestCase):
    def test_layout_engine_normalization_and_options(self) -> None:
        node_script = textwrap.dedent(
            """
            import assert from "node:assert/strict";
            import {
              chatLayoutEngineOptions,
              CHAT_LAYOUT_ENGINE_CLASSIC,
              CHAT_LAYOUT_ENGINE_FLEXLAYOUT,
              DEFAULT_CHAT_LAYOUT_ENGINE,
              normalizeChatLayoutEngine
            } from "./web/src/chatLayoutEngines.js";

            assert.equal(CHAT_LAYOUT_ENGINE_CLASSIC, "classic");
            assert.equal(CHAT_LAYOUT_ENGINE_FLEXLAYOUT, "flexlayout");
            assert.equal(DEFAULT_CHAT_LAYOUT_ENGINE, CHAT_LAYOUT_ENGINE_CLASSIC);

            assert.equal(normalizeChatLayoutEngine("classic"), "classic");
            assert.equal(normalizeChatLayoutEngine("Classic"), "classic");
            assert.equal(normalizeChatLayoutEngine("flexlayout"), "flexlayout");
            assert.equal(normalizeChatLayoutEngine("FLEXLAYOUT"), "flexlayout");
            assert.equal(normalizeChatLayoutEngine(""), "classic");
            assert.equal(normalizeChatLayoutEngine(undefined), "classic");
            assert.equal(normalizeChatLayoutEngine("unknown-engine"), "classic");

            const options = chatLayoutEngineOptions();
            assert.equal(options.length, 2);
            assert.deepEqual(
              options.map((option) => option.value),
              ["classic", "flexlayout"]
            );
            assert.deepEqual(
              options.map((option) => option.label),
              ["Classic", "FlexLayout"]
            );
            """
        )

        result = subprocess.run(
            ["node", "--input-type=module", "-e", node_script],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Node chat layout engine test failed:\\nSTDOUT:\\n{result.stdout}\\nSTDERR:\\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
