---
name: specpack
description: Generate an implementation-ready ExecPlan doc pack under docs for a feature, with class-level C++/Python/Javascript design, verification commands, and an ambiguity register. Use before any implementation.
---

# specpack

## Inputs required from user
- subsystem: one of {av, pipelines, platforms, simulation, gui, analysis, app}
- feature_name: kebab-case
- short_description: 3-10 sentences

## Hard gating
If the user requests design-only phase first:
- Do NOT edit product source code outside docs/<subsystem>/<feature_name>/.
- Do NOT run implementation/build/lint commands for product changes.
- Only write/update docs for review under docs/<subsystem>/<feature_name>/.

## Workflow
1) Create docs/<subsystem>/<feature_name>/ExecPlan.md (single living spec).
2) Populate sections: goals/non-goals, scope/non-scope, user stories & acceptance, interfaces/data, class inventory (C++/Python/Javascript/etc), error model, concurrency model, verification plan (./make.sh), PR evidence plan, ambiguity register.
3) Spawn sub-agents: explorer, multiple Spark `spec_reviewer` agents, and `naive_implementer`.
4) Use divide-and-conquer review coverage across implementability detail, software-bug risk/failure modes, and architecture/test quality.
5) Merge their findings into ExecPlan.md as concrete edits.

## Output contract
- Produce only updated files.
- End with SPEC COMPLETE or SPEC BLOCKED and list blocking questions (if any).
