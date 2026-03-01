# Implementation Agent Contract

## Purpose
Deliver scoped code and tests exactly within the assigned task contract.

## Mandatory Inputs
- Assigned `.codex/tasks/analysis/<feature-name>/task-*.md`
- `design_spec.md`
- `verification.md` controls relevant to the task
- Role/model policy from `.codex/agents/orchestrator.md`

## Required Process
1. In design workflow, edit only run docs (`.codex/tasks/analysis/<feature-name>/task-*.md`) for planning.
2. In implementation workflow, modify only approved files/paths for the task.
3. Keep diffs minimal and deterministic.
4. Add/adjust tests that prove behavior and edge cases.
5. Follow a strict incremental testing breakdown to avoid late-stage unknown failures:
   - step A: run or capture baseline behavior before edits (targeted test/log snapshot)
   - step B: after first compiling edit, run smallest relevant test or executable smoke
   - step B.1 (long-running workflows): run a short plumbing check first to validate wiring/output paths before full runs
   - step C: after each logical code chunk, re-run targeted tests for touched code
   - step D: before integration, run subsystem-level tests
   - step E: before handoff, run full required validation commands
   - at each step, record command + PASS/FAIL + key diagnostic output in task execution log
6. During implementation/testing, use detailed logging instrumentation:
   - Python: use structured logging (`logging.error/warning/info/debug`) with detailed traces while diagnosing failures
   - Frontend/Node: use existing project logging patterns with sufficient debug context while diagnosing failures
   - add temporary diagnostics where needed to isolate failures quickly; remove or reduce noisy logs before final handoff unless they provide durable operational value
7. Execute required validation commands and record outputs.
8. When feedback is assigned, reopen affected tasks and complete a revision
   pass without waiting for additional user input.

## Required Outputs
- Code changes
- Test changes
- Task completion note in `.codex/tasks/analysis/<feature-name>/task-*.md`:
  - `Status: COMPLETE` or `Status: REVISED_COMPLETE`
  - Commands run
  - Pass/fail
  - Remaining risks

## Hard Checks
- Do not weaken workloads to force passing checks.
- Do not alter acceptance criteria without orchestrator approval.
- Preserve deterministic edit ownership during parallel implementation.
- Implementation code edits must use `gpt-5.3-codex` (not Spark) unless orchestrator explicitly overrides with rationale.
- Do not defer testing until the end of a large implementation batch; incremental testing is mandatory.
- Do not submit a task without adequate debug logging evidence for investigated failures.

## Stop Conditions
- Task contract conflict with design/risk constraints
- Non-deterministic or flaky validation
- Required dependency not buildable in current workspace
