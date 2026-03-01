# Agent Gotchas

Purpose: record recurring high-cost failures and first-try fixes.

## Entry format

- Symptom
- Root cause
- First-try fix
- Verification
- Scope

## Known gotchas

### PR body update via `gh pr edit` fails

- Symptom: `gh pr edit --body-file ...` fails (GraphQL/Projects deprecation path).
- Root cause: `gh pr edit` can hit deprecated GraphQL fields in this environment.
- First-try fix: `gh api repos/<owner>/<repo>/pulls/<number> -X PATCH --raw-field body="$(cat <body-file>)"`
- Verification: confirm updated `body` in API response or PR page.
- Scope: PR body edits in this repository environment.

### Docker-in-Docker config mount resolves as directory

- Symptom: `Failed to read config file ... config.toml: Is a directory`.
- Root cause: mount source path is not daemon-visible as the expected file.
- First-try fix: move runtime inputs to daemon-visible host paths; avoid container-local `/tmp` mount sources; stage files under `/workspace/tmp` and re-run.
- Verification: `docker run --rm -v <host-file>:/etc/alpine-release alpine:3.20 sh -lc 'test -f /etc/alpine-release'` succeeds; chat starts cleanly.
- Scope: hub/tests launching runtime containers through host daemon.

### Runtime container cannot reach hub using `host.docker.internal`

- Symptom: startup/readiness hangs or fails; container-side `curl http://host.docker.internal:<port>/api/state` returns connection failure.
- Root cause: daemon network namespace does not provide a working `host.docker.internal` route for these containers.
- First-try fix: start hub with `--host 0.0.0.0` and set `--artifact-publish-base-url` to a container-reachable host/IP (often `$(hostname -I | awk '{print $1}')` in this environment).
- Verification: `docker run --rm alpine:3.20 sh -lc 'wget -q -T 2 -O - http://<host-ip>:<port>/api/state >/dev/null'` succeeds; chat `ready_ack_at` populates.
- Scope: local integration and manual runtime launches in Docker-in-Docker environments.

### `submit_artifact` returns `Artifact file not found` for existing runtime files

- Symptom: `submit_artifact` fails with `404` and detail `Artifact file not found: /workspace/...` even though the file exists in the runtime container.
- Root cause: artifact submissions sent JSON path references (`{\"path\":\"...\"}`), which required hub host filesystem visibility of runtime paths.
- First-try fix: submit file bytes over the network (`application/octet-stream`), with artifact name in `x-agent-hub-artifact-name`, instead of path-based JSON payloads.
- Verification: `submit_artifact` succeeds for:
  - runtime tmp file (`/workspace/tmp/<file>`)
  - absolute workspace file (`/workspace/<repo>/<file>`)
  - without host path mapping/rewrite logic
- Scope: artifact submission from runtime MCP tool in Docker-in-Docker path-mismatch environments.

### Hooks installed in setup snapshot are missing in new chats

- Symptom: setup build logs show `pre-commit installed at .git/hooks/pre-commit`, but fresh chats do not have hooks.
- Root cause: runtime mounted host checkout over container repo path, and chat clones do not inherit `.git/hooks`.
- First-try fix: use snapshot-backed image workspace mode (`--project-in-image`) so setup copies repo into image and runs hook install there.
- Verification: create two fresh chats on same snapshot and confirm `.git/hooks/pre-commit` exists in both without re-running setup.
- Scope: snapshot-based chat launches where hook state must be shared across chats.

### Runtime image build fails with `unable to find user root`

- Symptom: `docker build` fails in `docker/agent_cli/Dockerfile` at apt layers with `unable to find user root: no matching entries in passwd file`.
- Root cause: the chosen `BASE_IMAGE` declares `User=root` but does not include a `root` passwd entry; `USER root` username resolution fails before package-install layers.
- First-try fix: use numeric root (`USER 0`) in runtime Dockerfile and snapshot commit metadata.
- Verification: build setup runtime with a base image missing `root` passwd entry and confirm apt layers execute.
- Scope: setup/runtime image builds using non-standard base images.

### Yarn install fails after transient `@esbuild/*` registry errors

- Symptom: `corepack yarn install --frozen-lockfile` shows `502 Bad Gateway` for `@esbuild/*` tarballs and can follow with `ENOENT ... .yarn-metadata.json` during linking.
- Root cause: transient package fetch failure leaves Yarn v1 cache state unusable for the same install attempt.
- First-try fix: retry install once after `corepack yarn cache clean` in Docker build steps.
- Verification: inject a failing first install attempt and confirm second pass succeeds with cleaned cache.
- Scope: Docker builds running Yarn v1 installs for `web/` dependencies.
