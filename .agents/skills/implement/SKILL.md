---
name: implement
description: Implement a feature exactly per the feature ExecPlan.md under docs, run minimal required verification with ./make.sh, and prepare PR evidence per AGENTS.md.
---

# implement

## Preconditions
- User has explicitly approved moving from design-only to implementation.
- ExecPlan.md exists and is marked SPEC COMPLETE.

## Workflow
1) Read ExecPlan.md completely.
2) Ask explorer for code entry points and integration points.
3) Decompose the ExecPlan into 2-4 owned implementation slices that can proceed in parallel without file conflicts. Partition by the largest architectural seams first, not by tiny cleanup tasks.
4) Spawn multiple worker agents using the Spark worker profile. Assign each worker one owned slice, concrete file boundaries, and explicit validation responsibilities.
5) Require workers to start with the biggest/highest-risk feature changes first. Small refactors, naming cleanup, and cosmetic follow-up edits happen only after the core feature slices are landed and validated.
6) Integrate worker output continuously. If a large slice is blocked, unblock or re-slice it; do not avoid it by finishing low-value cleanup first.
7) Run verification commands from ExecPlan.md using the smallest command set that still proves correctness, plus any targeted checks needed after each major slice lands.
8) Spawn multiple spec_reviewer agents using a divide-and-conquer review plan. At minimum, split review across:
   - ExecPlan coverage and missing requirement drift
   - software bugs, edge cases, and regression risk
   - architecture/integration quality and test adequacy
9) Do not conclude the chat while any reviewer still reports missing implementation, poor implementation quality, bugs, or architecture problems. Fix issues, re-run targeted validation, and re-review until the reviewer set explicitly says the ExecPlan is FULLY implemented, implemented well, and bug free.
10) Wait long enough for reviews to finish before concluding the turn; use a reviewer wait timeout of at least 10 minutes unless the user asked for faster iteration.
