## Findings
- [High] Callback 502 occurred when daemon host route was not represented by existing candidate hosts.
- [Medium] Prior implementation lacked actionable callback-forward diagnostics.
- [Medium] Upstream target logs risked exposing callback query values before redaction controls.

## Reproduction
1. Create active browser-callback session.
2. Force localhost/request/default candidates to fail while bridge host would succeed.
3. Observe pre-fix HTTP 502 and missing bridge target.

## Suggested Fixes
- Append deterministic bridge host candidates after existing hosts.
- Add structured redacted logging for resolution decisions, upstream attempts, and failure reasons.
- Add tests for redaction and error classification.

## Residual Concerns
- Unusual network overlays may still need additional host discovery adapters.
