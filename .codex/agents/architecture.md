# Architecture Agent Contract

## Purpose
Produce implementation-ready design boundaries that keep changes reviewable and
minimize coupling/regressions.

## Mandatory Inputs
- `feature_plan.md`
- `verification.md`
- Relevant module ownership and repository topology

## Required Process
1. Define interfaces and data flow changes.
2. Identify impacted modules/services/tests.
3. Confirm build graph impact and migration strategy.
4. Explicitly describe rollback strategy.
5. Update design boundaries for every user feedback revision cycle.
6. In design workflow, produce implementation-ready docs without code edits.

## Required Outputs
- `design_spec.md` including:
  - `## Design Goals`
  - `## Non-Goals`
  - `## Interfaces`
  - `## Data Flow`
  - `## Build/Test Impact`
  - `## Rollback Plan`

## Hard Checks
- Design must avoid generated artifacts and vendor directories unless explicitly requested.
- Interfaces must include compatibility assumptions.
- Feedback-driven design changes must keep task path ownership deterministic.

## Stop Conditions
- Interface ambiguity that blocks deterministic implementation
- Missing test strategy for changed public behavior
- Unbounded blast radius across modules
