# Validation Report

## Scope
Describe what was validated and why the selected commands are sufficient.

## Environment
- Branch:
- Commit:
- Host/Container:
- Toolchain notes:
- Revision cycle:

## Command Results
| Command | Status | Notes |
|---|---|---|
| `uv run pytest tests/<targeted_test>.py` | PASS/FAIL | |
| `uv run pytest tests/test_hub_and_cli.py -k <targeted_case>` | PASS/FAIL | |
| `cd web && yarn build` | PASS/FAIL | Frontend changes only |

## Control Verification
Map each control to validation evidence.

## Benchmark Evidence
Include entries with `Function`, `Scope`, and `Timing`.

## Residual Risks
List any unresolved risk with owner and mitigation plan.
