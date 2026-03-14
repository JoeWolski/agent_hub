# Mount Decision Log (AOH-03)

Date: 2026-03-01
Status: Closed

## Kept Decisions
- Keep daemon-visible mount source rewrite branches required for Docker-in-Docker compatibility.
- Keep container-reachable callback host routing branches as approved network exception logic.

## Changed In This Cycle
- Identity defaults were tightened to config-first behavior for CLI/Hub runtime identity inputs.
- Non-DIND quiet fallback behavior in runtime/state agent-type and runtime-image resolution paths was removed.

## Decision Outcome
- Approved DIND exception branches remain.
- Non-DIND fallback branches in scope runtime/state paths are pruned for this cycle.
