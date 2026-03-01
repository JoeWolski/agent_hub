# Feature Plan: Project-In-Image Runtime Writability

## Problem Statement
When project snapshots are baked into images, new chat runtimes can start with a repository tree that is not writable by the runtime user. This breaks basic file edits (for example, `touch`, `git add`, and editor writes) in fresh chat windows.

Recent commits attempted to fix this with an ownership repair step (`chown -R uid:gid`) before `docker commit`, but failures continue in real hub flows.

## What We Learned From Recent Commits
- `fe8378e` / `0eb06f6`: introduced project-in-image snapshot flow and conditional skip of project bind mount.
- `7f4b5da`: added ownership repair in CLI, but gated it behind `project_in_image=True`.
- `ead7bb1`: bumped snapshot schema and fixed Codex trust config injection, but did not address when ownership repair runs.
- Current hub snapshot-build path uses `prepare_snapshot_only=True` and does not pass `project_in_image=True`, so the repair path is skipped during the image build that chats reuse.

## Goals
- Guarantee `/workspace/<project>` is writable by the actual runtime user in every new chat using snapshot-backed project-in-image mode.
- Make this guarantee deterministic across cached and newly built snapshots.
- Add regression coverage that exercises hub snapshot-build + chat-launch integration path, not only CLI command construction.

## Non-Goals
- No changes to frontend UI behavior.
- No changes to git credential/auth behavior.
- No broad permission broadening such as `chmod -R 777`.

## Scope
- Snapshot build command composition in hub server.
- Snapshot ownership repair trigger in CLI.
- Snapshot readiness/invalidations for stale images.
- Tests for project snapshot build and chat launch writability invariants.

## Proposed Approach (High Level)
1. Ensure hub snapshot build path explicitly enables project-in-image semantics so ownership repair runs on the snapshot that will be reused.
2. Make ownership repair independent from launch-mode flags by tying it to whether in-image workspace copy occurred in the setup container.
3. Add a post-build verification probe in setup flow that fails fast if runtime user cannot write to container project path.
4. Add targeted tests for:
   - snapshot prepare command includes project-in-image mode where required,
   - ownership repair executes in the project snapshot build path,
   - new chat launch profile built from that snapshot remains writable.

## Acceptance Criteria
- A freshly built project snapshot used by a new chat allows runtime user write operations under `container_project_path`.
- If ownership repair fails, snapshot build fails before commit with actionable error output.
- Tests fail if hub snapshot build path regresses to a mode that skips repair.
- Existing non-project-in-image workflows remain unchanged.

## PR Evidence Plan
- Required artifacts:
  - `validation/manifest.txt` with exact commands and pass/fail.
  - `validation/validation_report.md` mapping each acceptance criterion to test evidence.
  - `verification_report.md` + `fresh_audit_report.md`.
- Visual evidence:
  - Not required (backend/runtime behavior only). If added later, use `.png` only.
- Self-review criteria before PR inclusion:
  - command logs correspond to the final head commit,
  - no failed required checks omitted,
  - evidence maps directly to each acceptance criterion.
