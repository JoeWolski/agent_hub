# Agent Hub Hub-Container Images

These images are for running the `agent_hub` control plane itself.

They are separate from the existing chat runtime image at `docker/Dockerfile`, which is still used for per-chat execution environments launched by `agent_cli`.

## Images

- `production`: runs `./bin/agent_hub` with a prebuilt frontend (`--no-frontend-build` by default).
- `development`: includes extra tooling for development/demo workflows:
  - `nodejs` + `corepack`
  - `ffmpeg`, `xvfb`, `xdotool`, `jq`
  - Playwright Firefox browser + Linux dependencies

## Build

```bash
# Production image
docker build \
  -f docker/agent_hub/Dockerfile \
  --target production \
  -t agent-hub:prod .

# Development image
docker build \
  -f docker/agent_hub/Dockerfile \
  --target development \
  -t agent-hub:dev .
```

## Run Production

Because `agent_hub` launches nested chat containers through the host Docker daemon, host paths must be reachable by the host daemon with the same absolute path values used inside this container.

```bash
export AGENT_HUB_SHARED_ROOT=/tmp/agent_hub_shared
mkdir -p "${AGENT_HUB_SHARED_ROOT}"

docker run --rm -it \
  -p 8765:8765 \
  -e AGENT_HUB_SHARED_ROOT="${AGENT_HUB_SHARED_ROOT}" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "${AGENT_HUB_SHARED_ROOT}:${AGENT_HUB_SHARED_ROOT}" \
  agent-hub:prod
```

Then open `http://127.0.0.1:8765`.

The production entrypoint:

- verifies Docker socket presence
- verifies `AGENT_HUB_SHARED_ROOT` is a bind mount (unless bypassed)
- initializes config/data/home under `${AGENT_HUB_SHARED_ROOT}`
- executes `./bin/agent_hub`

## Run Development

```bash
export AGENT_HUB_SHARED_ROOT=/tmp/agent_hub_shared
mkdir -p "${AGENT_HUB_SHARED_ROOT}"

docker run --rm -it \
  -p 8765:8765 \
  -e AGENT_HUB_SHARED_ROOT="${AGENT_HUB_SHARED_ROOT}" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "${AGENT_HUB_SHARED_ROOT}:${AGENT_HUB_SHARED_ROOT}" \
  -v "$(pwd):/opt/agent_hub" \
  agent-hub:dev
```

From inside the dev container:

```bash
./bin/agent_hub --data-dir "${AGENT_HUB_SHARED_ROOT}/data" --config-file "${AGENT_HUB_SHARED_ROOT}/config/agent.config.toml"
```

For demo generation workflows:

```bash
cd tools/demo
npm run all
```
