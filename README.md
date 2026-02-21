# Agent Hub (Ubuntu 22.04)

This repository uses a Python `uv` tool (`agent_cli`) to launch a containerized agent runtime.

It also includes `agent_hub`, a local web control panel for project chat orchestration.

## What it does

- Builds and runs the `docker/Dockerfile` for the agent environment.
- Supports an optional intermediate base image build from a provided Dockerfile/path.
- Mounts your project under a stable container path:
  `/home/<local_user>/projects/<project-name>`
- Mounts persistent agent state on the host.
- Supports read-only and read-write mount overrides.
- Supports `--resume` to continue the latest session for the project.

## Requirements

- Docker and `nvidia-container-toolkit` for GPU mode.
- Node.js and Yarn (for the React frontend in `web/`).

## Quick start

```bash
uv run agent_cli --project /path/to/project
```

Defaults for `--project` is `.`.

## Common options

- `--project PATH`
- `--resume`
- `--config-file PATH` (default: repo `config/agent.config.toml`)
- `--credentials-file PATH` and/or `--openai-api-key`
- `--base PATH` (Dockerfile path or directory with Dockerfile)
- `--base-image TAG` (default: `nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04`)
- `--ro-mount /host/path:/container/path`
- `--rw-mount /host/path:/container/path`
- `--env-var KEY=VALUE` (repeatable)
- `--setup-script "cmd1\ncmd2"` and `--snapshot-image-tag TAG` (build/reuse a setup snapshot image)
- `--prepare-snapshot-only` (build/reuse snapshot and exit)
- `--local-user`, `--local-group`, `--local-uid`, `--local-gid`
- `--local-supplementary-gids`, `--local-supplementary-groups`, `--local-umask`
- `--agent-home-path PATH`

## Examples

Use a different project and pass through a command:

```bash
uv run agent_cli --project /path/to/project -- bash -lc 'id && pwd'
```

Build/run against a custom base Dockerfile:

```bash
uv run agent_cli --project /path/to/project --base /path/to/base/Dockerfile
```

Add mounts:

```bash
uv run agent_cli \
  --project /path/to/project \
  --ro-mount /mnt/datasets:/mnt/datasets \
  --rw-mount /var/ccache_cache:/var/ccache_cache \
  --env-var WANDB_MODE=offline
```

Resume last session:

```bash
uv run agent_cli --project /path/to/project --resume
```

## Usage model

- Supported launcher: `uv run agent_cli`.
- All behavior is controlled with CLI arguments.

## Local web panel (`agent_hub`)

Build the React frontend first:

```bash
cd web
yarn install
yarn build
```

`uv run agent_hub` now auto-builds the frontend when needed, so the manual build step above is optional.

```bash
uv run agent_hub
```

Optional:

```bash
uv run agent_hub --data-dir /path/to/state --config-file /path/to/config.toml --host 127.0.0.1 --port 8765
```

Then open:

```bash
http://127.0.0.1:8765
```

To access from another machine on the same network:

```bash
uv run agent_hub --host 0.0.0.0 --port 8765
```

Then open:

```bash
http://<hub-host-ip>:8765
```

Frontend development (React + Vite, with API proxy to `agent_hub`):

```bash
cd web
yarn dev --host 0.0.0.0 --port 5173
```

Capabilities:

- Add projects by Git repository URL.
- Add/create a project-level setup snapshot container image at project creation time (and rebuild on project settings changes).
- Start chats immediately with no chat-start configuration prompts; each new chat launches from the project snapshot image.
- Set a per-project setup script in the UI (multiline; each non-empty line runs sequentially in the container with the checked-out project as working directory).
- Setup snapshots are cached per project and reused for new chats (cache key changes when setup/base/default mount/default env settings change).
- Set a per-project base image source as either a Docker image tag or a Dockerfile path/directory inside the checked-out repo.
- Configure default/new-chat volumes with `Add volume` UI widgets (local path, container path, read-only/read-write mode).
- Configure default/new-chat environment variables with `Add environment variable` UI widgets.
- Close chats (workspace is reset to the remote default branch and reused).
- Delete chats explicitly from the UI (this removes that workspace).
- Each chat shows both the host workspace path and the container working folder.
