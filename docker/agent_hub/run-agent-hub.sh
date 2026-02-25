#!/usr/bin/env bash

set -euo pipefail

if [[ $# -gt 0 && "${1}" != -* ]]; then
  exec "$@"
fi

if [[ ! -S /var/run/docker.sock ]]; then
  cat >&2 <<'EOF'
ERROR: /var/run/docker.sock is not available.
agent_hub needs Docker daemon access to launch chat containers.
Mount the host socket with:
  -v /var/run/docker.sock:/var/run/docker.sock
EOF
  exit 1
fi

shared_root="$(realpath -m "${AGENT_HUB_SHARED_ROOT:-/tmp/agent_hub_shared}")"
data_dir="${AGENT_HUB_DATA_DIR:-${shared_root}/data}"
config_file="${AGENT_HUB_CONFIG_FILE:-${shared_root}/config/agent.config.toml}"
home_dir="${AGENT_HUB_HOME:-${shared_root}/home}"
host="${AGENT_HUB_HOST:-0.0.0.0}"
port="${AGENT_HUB_PORT:-8765}"
artifact_base_url="${AGENT_ARTIFACT_PUBLISH_BASE_URL:-http://host.docker.internal:${port}}"
frontend_build="${AGENT_HUB_FRONTEND_BUILD:-0}"

mkdir -p "${data_dir}" "$(dirname "${config_file}")" "${home_dir}"
if [[ ! -f "${config_file}" ]]; then
  cp /opt/agent_hub/config/agent.config.toml "${config_file}"
fi

if ! awk -v mount_point="${shared_root}" '$5 == mount_point {found = 1} END {exit !found}' /proc/self/mountinfo; then
  if [[ "${AGENT_HUB_ALLOW_UNMOUNTED_SHARED_ROOT:-0}" != "1" ]]; then
    cat >&2 <<EOF
ERROR: ${shared_root} is not a bind mount.
This container talks to the host Docker daemon, so all paths used for chats must exist on the host with identical absolute paths.
Run with a same-path bind mount, for example:
  -v ${shared_root}:${shared_root}
Set AGENT_HUB_ALLOW_UNMOUNTED_SHARED_ROOT=1 to bypass this safety check.
EOF
    exit 1
  fi
fi

export HOME="${home_dir}"

args=(
  "--host" "${host}"
  "--port" "${port}"
  "--data-dir" "${data_dir}"
  "--config-file" "${config_file}"
  "--artifact-publish-base-url" "${artifact_base_url}"
)

if [[ "${frontend_build}" == "1" ]]; then
  args+=("--frontend-build")
else
  args+=("--no-frontend-build")
fi

exec /opt/agent_hub/bin/agent_hub "${args[@]}" "$@"
