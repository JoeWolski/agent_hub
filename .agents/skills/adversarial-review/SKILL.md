---
name: adversarial-review
description: Run adversarial reviewers against a feature ExecPlan.md under docs and output concrete spec diffs required for naive-agent implementability.
---

# adversarial-review

## Inputs
- execplan_path: docs/<subsystem>/<feature>/ExecPlan.md

## Workflow
1) Spawn multiple Spark `spec_reviewer` agents plus at least one `naive_implementer`.
2) Use a divide-and-conquer review split so reviewers attack different concerns in parallel:
   - implementability / missing detail / ambiguity
   - software bugs, failure modes, and unsafe assumptions
   - architecture quality, layering, ownership, and test gaps
3) Consolidate into a single verdict: IMPLEMENTABLE_BY_NOVICE = yes/no.
4) If no, output exact spec diffs to fix.
5) If yes, still report any non-blocking architecture or bug-risk concerns that should be improved before implementation starts.
