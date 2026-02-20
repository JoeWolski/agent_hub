# Codex Docker (Ubuntu 22.04)

This setup runs OpenAI Codex inside an Ubuntu 22.04 container and mounts your project at:

`$HOME/projects/<project-name>`

## What this gives you

- Ubuntu 22.04 container
- Codex CLI preinstalled
- Full GPU access enabled (`gpus: all`)
- Your chosen project directory mounted at `$HOME/projects/<project-name>` in the container
- Persistent Codex home mounted at `/home/<your-user>` (default host path: `~/.codex-docker-home/<your-user>`)
- Runtime identity mirrors the launcher user (`name`, `uid`, `gid`, supplementary groups, and `umask`)
- Working directory starts in the mounted project path (not the parent `projects` folder)
- Re-run on the same project starts a new conversation by default
- Use `--resume` to continue the last Codex session for that project
- `sudo` is available for the mapped user inside the container
- No package/tool installs on your host machine

## Prerequisites

- Docker with Compose plugin (`docker compose`)
- NVIDIA GPU driver + `nvidia-container-toolkit` installed on the host
- Optional: `OPENAI_API_KEY` (env var or `.credentials` file)

## Run

```bash
chmod +x run_codex.sh
./run_codex.sh
```

By default, `PROJECT_PATH` is your current directory (`$PWD`).
If you rerun `run_codex.sh` from the same `PROJECT_PATH` and a previous session exists,
it resumes that project session automatically.

To run against any project directory:

```bash
PROJECT_PATH="$HOME/projects/any-repo" ./run_codex.sh
```

If `PROJECT_PATH="$HOME/projects/any-repo"`, container cwd will be:

`$HOME/projects/any-repo`

You can resume the previous session in the same project with:

```bash
PROJECT_PATH="/path/to/project" ./run_codex.sh --resume
```

Optional: choose where Codex home/auth state lives on your host:

```bash
CODEX_HOME_PATH="$HOME/.cache/codex-home" ./run_codex.sh
```

Optional: use a different Codex defaults file:

```bash
CODEX_CONFIG_FILE="$HOME/.config/codex/config.toml" ./run_codex.sh
```

Optional: override the base image used by this Codex container:

```bash
BASE_IMAGE="your-local-base-image:tag" ./run_codex.sh
```

Preferred: pass only a local base path (directory with `Dockerfile`, or Dockerfile path):

```bash
./run_codex.sh --base "$HOME/projects/av/ci/x86_docker"
```

or:

```bash
./run_codex.sh --base "$HOME/projects/av/ci/x86_docker/Dockerfile.x86"
```

Default behavior for `--base`:
- Uses the provided Dockerfile directory as build context.
- Auto-generates a stable project-specific base image tag.
- No extra env vars required.

Advanced/legacy env-driven base override still supported:

```bash
BASE_DOCKER_CONTEXT="$HOME/projects/av/ci/x86_docker" ./run_codex.sh
```

Optional: add extra read-only mounts at launch (repeatable):

```bash
./run_codex.sh \
  --ro-mount "$HOME/datasets:/mnt/datasets" \
  --ro-mount "$HOME/models:/mnt/models"
```

Optional: add extra read-write mounts at launch (repeatable):

```bash
./run_codex.sh \
  --rw-mount "/var/ccache_cache:/var/ccache_cache" \
  --rw-mount "$HOME/work-cache:/mnt/work-cache"
```

If you only want to add host ccache into the container:

```bash
./run_codex.sh --rw-mount "/var/ccache_cache:/var/ccache_cache"
```

Optional: override identity mapping variables (normally auto-detected):

```bash
LOCAL_USER="$(id -un)" \
LOCAL_GROUP="$(id -gn)" \
LOCAL_UID="$(id -u)" \
LOCAL_GID="$(id -g)" \
LOCAL_SUPP_GIDS="$(id -G | tr ' ' ',')" \
LOCAL_SUPP_GROUPS="$(id -Gn | tr ' ' ',')" \
LOCAL_UMASK="$(umask)" \
./run_codex.sh
```

If you prefer a credentials file, create `.credentials` next to `run_codex.sh`:

```bash
cp .credentials.example .credentials
# then edit .credentials with your key
```

If no API key is set, the container still starts so you can use Codex external device login.
If both are set, exported `OPENAI_API_KEY` takes precedence over `.credentials`.
`codex.config.toml` intentionally does not contain credentials.

To use a different credentials file path:

```bash
CREDENTIALS_FILE="$HOME/.config/codex/.credentials" ./run_codex.sh
```

Optional:

```bash
PROJECT_PATH="$HOME/projects/some-other-repo" ./run_codex.sh
```

To start a shell in the same container instead of launching Codex directly:

```bash
./run_codex.sh bash
```

Use `--` if your command includes flags that should not be parsed by the launcher:

```bash
./run_codex.sh --rw-mount "/var/ccache_cache:/var/ccache_cache" -- bash -lc 'ls -la /var/ccache_cache | head'
```

Sudo verification inside container:

```bash
./run_codex.sh bash -lc 'sudo -n whoami'
```

GPU verification inside the container:

```bash
./run_codex.sh bash -lc 'nvidia-smi'
```

Quick verification that file ownership is preserved:

```bash
PROJECT_PATH="$HOME/projects/any-repo" ./run_codex.sh bash -lc 'id && pwd && touch .perm-test'
ls -ln "$HOME/projects/any-repo/.perm-test"
```
