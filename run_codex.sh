#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDENTIALS_FILE="${CREDENTIALS_FILE:-$SCRIPT_DIR/.credentials}"

export LOCAL_USER="${LOCAL_USER:-$(id -un)}"
export LOCAL_GROUP="${LOCAL_GROUP:-$(id -gn)}"
export LOCAL_UID="${LOCAL_UID:-$(id -u)}"
export LOCAL_GID="${LOCAL_GID:-$(id -g)}"
export LOCAL_SUPP_GIDS="${LOCAL_SUPP_GIDS:-$(id -G | tr ' ' ',')}"
export LOCAL_SUPP_GROUPS="${LOCAL_SUPP_GROUPS:-$(id -Gn | tr ' ' ',')}"
export LOCAL_UMASK="${LOCAL_UMASK:-$(umask)}"
export CONTAINER_HOME="${CONTAINER_HOME:-/home/$LOCAL_USER}"
export PROJECT_PATH="${PROJECT_PATH:-$PWD}"
export CODEX_HOME_PATH="${CODEX_HOME_PATH:-$HOME/.codex-docker-home/$LOCAL_USER}"
export CODEX_CONFIG_FILE="${CODEX_CONFIG_FILE:-$SCRIPT_DIR/codex.config.toml}"
export BASE_IMAGE="${BASE_IMAGE:-}"
export BASE_DOCKER_PATH="${BASE_DOCKER_PATH:-}"
export BASE_DOCKER_CONTEXT="${BASE_DOCKER_CONTEXT:-}"
export BASE_DOCKERFILE="${BASE_DOCKERFILE:-}"
export BASE_IMAGE_TAG="${BASE_IMAGE_TAG:-}"

RO_MOUNTS=()
RW_MOUNTS=()
CONTAINER_ARGS=()

parse_mount_spec() {
  local mount_spec="$1"
  local flag_name="$2"

  if [[ "$mount_spec" != *:* ]]; then
    echo "Invalid $flag_name value: $mount_spec (expected /host/path:/container/path)." >&2
    exit 1
  fi

  local host_path="${mount_spec%%:*}"
  local container_path="${mount_spec#*:}"

  if [[ -z "$host_path" || -z "$container_path" ]]; then
    echo "Invalid $flag_name value: $mount_spec (expected /host/path:/container/path)." >&2
    exit 1
  fi

  if [[ "${container_path:0:1}" != "/" ]]; then
    echo "Invalid container path in $flag_name: $container_path (must be absolute)." >&2
    exit 1
  fi

  if [[ ! -e "$host_path" ]]; then
    echo "Host path in $flag_name does not exist: $host_path" >&2
    exit 1
  fi

  printf '%s:%s\n' "$host_path" "$container_path"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --base (expected /path/to/Dockerfile or Dockerfile directory)." >&2
        exit 1
      fi
      BASE_DOCKER_PATH="$2"
      shift 2
      ;;
    --base=*)
      BASE_DOCKER_PATH="${1#*=}"
      shift
      ;;
    --ro-mount)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --ro-mount (expected /host/path:/container/path)." >&2
        exit 1
      fi
      mount_spec="$2"
      parsed_mount="$(parse_mount_spec "$mount_spec" "--ro-mount")"
      RO_MOUNTS+=("${parsed_mount}:ro")
      shift 2
      ;;
    --rw-mount)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --rw-mount (expected /host/path:/container/path)." >&2
        exit 1
      fi
      mount_spec="$2"
      parsed_mount="$(parse_mount_spec "$mount_spec" "--rw-mount")"
      RW_MOUNTS+=("$parsed_mount")
      shift 2
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        CONTAINER_ARGS+=("$1")
        shift
      done
      ;;
    *)
      CONTAINER_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${OPENAI_API_KEY:-}" && -f "$CREDENTIALS_FILE" ]]; then
  key_value="$(
    sed -n 's/^[[:space:]]*OPENAI_API_KEY[[:space:]]*=[[:space:]]*//p' "$CREDENTIALS_FILE" \
      | tail -n 1
  )"
  key_value="${key_value%$'\r'}"
  key_value="${key_value#\"}"
  key_value="${key_value%\"}"
  key_value="${key_value#\'}"
  key_value="${key_value%\'}"
  if [[ -n "$key_value" ]]; then
    export OPENAI_API_KEY="$key_value"
  fi
fi

if [[ ! -d "$PROJECT_PATH" ]]; then
  echo "Project path does not exist: $PROJECT_PATH" >&2
  echo "Set PROJECT_PATH to your repo path and try again." >&2
  exit 1
fi

PROJECT_PATH="$(cd "$PROJECT_PATH" && pwd)"
export PROJECT_PATH
export PROJECT_NAME="${PROJECT_NAME:-$(basename "$PROJECT_PATH")}"
export CONTAINER_PROJECT_PATH="${CONTAINER_PROJECT_PATH:-$CONTAINER_HOME/projects/$PROJECT_NAME}"

CODEX_CONFIG_FILE="$(cd "$(dirname "$CODEX_CONFIG_FILE")" && pwd)/$(basename "$CODEX_CONFIG_FILE")"
export CODEX_CONFIG_FILE

if [[ ! -f "$CODEX_CONFIG_FILE" ]]; then
  echo "Codex config file does not exist: $CODEX_CONFIG_FILE" >&2
  exit 1
fi

mkdir -p "$CODEX_HOME_PATH" "$CODEX_HOME_PATH/.codex" "$CODEX_HOME_PATH/projects"

to_abs_path() {
  local input_path="$1"
  if [[ "${input_path:0:1}" == "/" ]]; then
    printf '%s\n' "$input_path"
  else
    printf '%s/%s\n' "$(pwd)" "$input_path"
  fi
}

sanitize_tag_component() {
  local value
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_.-' '-')"
  value="${value##-}"
  value="${value%%-}"
  if [[ -z "$value" ]]; then
    value="base"
  fi
  printf '%s\n' "$value"
}

short_hash() {
  local value="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$value" | sha256sum | cut -c1-12
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$value" | shasum -a 256 | cut -c1-12
    return
  fi
  printf '%s' "$value" | cksum | awk '{print $1}'
}

resolved_context=""
resolved_dockerfile=""

if [[ -n "$BASE_DOCKER_PATH" ]]; then
  base_path_abs="$(to_abs_path "$BASE_DOCKER_PATH")"
  if [[ -d "$base_path_abs" ]]; then
    resolved_context="$(cd "$base_path_abs" && pwd)"
    resolved_dockerfile="$resolved_context/Dockerfile"
  elif [[ -f "$base_path_abs" ]]; then
    resolved_dockerfile="$(cd "$(dirname "$base_path_abs")" && pwd)/$(basename "$base_path_abs")"
    resolved_context="$(cd "$(dirname "$resolved_dockerfile")" && pwd)"
  else
    echo "Invalid --base/BASE_DOCKER_PATH: $BASE_DOCKER_PATH" >&2
    echo "Expected an existing Dockerfile path or directory containing Dockerfile." >&2
    exit 1
  fi
elif [[ -n "$BASE_DOCKER_CONTEXT" || -n "$BASE_DOCKERFILE" ]]; then
  resolved_context=""

  if [[ -n "$BASE_DOCKER_CONTEXT" ]]; then
    if [[ ! -d "$BASE_DOCKER_CONTEXT" ]]; then
      echo "BASE_DOCKER_CONTEXT does not exist or is not a directory: $BASE_DOCKER_CONTEXT" >&2
      exit 1
    fi
    resolved_context="$(cd "$BASE_DOCKER_CONTEXT" && pwd)"
  fi

  if [[ -n "$BASE_DOCKERFILE" ]]; then
    if [[ "${BASE_DOCKERFILE:0:1}" == "/" ]]; then
      resolved_dockerfile="$BASE_DOCKERFILE"
    elif [[ -n "$resolved_context" ]]; then
      resolved_dockerfile="$resolved_context/$BASE_DOCKERFILE"
    else
      resolved_dockerfile="$(cd "$(dirname "$BASE_DOCKERFILE")" && pwd)/$(basename "$BASE_DOCKERFILE")"
    fi
  else
    if [[ -z "$resolved_context" ]]; then
      echo "BASE_DOCKER_CONTEXT is required when BASE_DOCKERFILE is not set." >&2
      exit 1
    fi
    resolved_dockerfile="$resolved_context/Dockerfile"
  fi

  if [[ ! -f "$resolved_dockerfile" ]]; then
    echo "Base Dockerfile not found: $resolved_dockerfile" >&2
    exit 1
  fi

  if [[ -z "$resolved_context" ]]; then
    resolved_context="$(cd "$(dirname "$resolved_dockerfile")" && pwd)"
  fi

fi

if [[ -n "$resolved_dockerfile" ]]; then
  if [[ ! -f "$resolved_dockerfile" ]]; then
    echo "Base Dockerfile not found: $resolved_dockerfile" >&2
    exit 1
  fi

  if [[ -z "$resolved_context" ]]; then
    resolved_context="$(cd "$(dirname "$resolved_dockerfile")" && pwd)"
  fi

  if [[ -z "$BASE_IMAGE_TAG" ]]; then
    tag_project="$(sanitize_tag_component "$PROJECT_NAME")"
    tag_base="$(sanitize_tag_component "$(basename "$resolved_context")")"
    tag_hash="$(short_hash "$resolved_dockerfile")"
    BASE_IMAGE_TAG="codex-base-${tag_project}-${tag_base}-${tag_hash}"
  fi

  echo "Building base image '$BASE_IMAGE_TAG' from $resolved_dockerfile" >&2
  docker build -f "$resolved_dockerfile" -t "$BASE_IMAGE_TAG" "$resolved_context"
  export BASE_IMAGE="$BASE_IMAGE_TAG"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY not set. Starting without API key." >&2
  echo "Use Codex device login inside the container if needed." >&2
fi

cd "$SCRIPT_DIR"
cmd=(docker compose run --rm --build)
for rw_mount in "${RW_MOUNTS[@]}"; do
  cmd+=(--volume "$rw_mount")
done
for ro_mount in "${RO_MOUNTS[@]}"; do
  cmd+=(--volume "$ro_mount")
done
cmd+=(codex)
if [[ "${#CONTAINER_ARGS[@]}" -gt 0 ]]; then
  cmd+=("${CONTAINER_ARGS[@]}")
fi
exec "${cmd[@]}"
