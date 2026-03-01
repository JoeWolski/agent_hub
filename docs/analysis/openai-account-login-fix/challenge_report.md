## Findings
- [LOW] Identity propagation was previously implicit in chat/snapshot command flow, making regressions hard to detect if execution context changes.

## Reproduction
1. Inspect hub-generated `agent_cli` launch command before fix.
2. Observe missing explicit `--local-uid/--local-gid` arguments.
3. Verify identity depended on inherited process context.

## Suggested Fixes
- Pass explicit `--local-uid`/`--local-gid` from hub command assembly.
- Add direct assertions in snapshot/chat command composition tests.

## Residual Concerns
- Behavior still depends on hub process identity source (`os.getuid/os.getgid`) unless future settings allow user override.
