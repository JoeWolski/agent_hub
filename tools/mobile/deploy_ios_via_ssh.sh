#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

MAC_HOST=""
REMOTE_DIR="~/agent_hub_mobile"
APP_ID="com.agenthub.mobile"
APP_NAME="Agent Hub"
SERVER_URL=""
DEVICE_UDID=""
APPLE_TEAM_ID=""
SCHEME="App"
CONFIGURATION="Debug"
SKIP_INSTALL=0
RSYNC_DELETE=1

usage() {
  cat <<'USAGE'
Usage: tools/mobile/deploy_ios_via_ssh.sh [options]

Options:
  --mac-host <user@host>    SSH target for macOS builder (required)
  --remote-dir <path>       Remote repo path (default: ~/agent_hub_mobile)
  --server-url <url>        Hosted Agent Hub URL for the WebView
  --app-id <id>             iOS bundle identifier (default: com.agenthub.mobile)
  --app-name <name>         App display name (default: Agent Hub)
  --device-udid <udid>      Physical iPhone UDID connected to macOS (required)
  --apple-team-id <id>      Apple Developer Team ID (required)
  --scheme <name>           Xcode scheme (default: App)
  --configuration <name>    Build configuration (default: Debug)
  --skip-install            Skip remote "yarn install"
  --no-delete               Disable rsync --delete
  -h, --help                Show help

Example:
  tools/mobile/deploy_ios_via_ssh.sh \
    --mac-host dev@macmini.local \
    --server-url http://192.168.1.20:8765 \
    --device-udid 00008110-001234567890801E \
    --apple-team-id ABCD123456
USAGE
}

fail() {
  echo "error: $*" >&2
  exit 1
}

while (($# > 0)); do
  case "$1" in
    --mac-host)
      MAC_HOST="${2:-}"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="${2:-}"
      shift 2
      ;;
    --server-url)
      SERVER_URL="${2:-}"
      shift 2
      ;;
    --app-id)
      APP_ID="${2:-}"
      shift 2
      ;;
    --app-name)
      APP_NAME="${2:-}"
      shift 2
      ;;
    --device-udid)
      DEVICE_UDID="${2:-}"
      shift 2
      ;;
    --apple-team-id)
      APPLE_TEAM_ID="${2:-}"
      shift 2
      ;;
    --scheme)
      SCHEME="${2:-}"
      shift 2
      ;;
    --configuration)
      CONFIGURATION="${2:-}"
      shift 2
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --no-delete)
      RSYNC_DELETE=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "${MAC_HOST}" ]] || fail "--mac-host is required"
[[ -n "${DEVICE_UDID}" ]] || fail "--device-udid is required"
[[ -n "${APPLE_TEAM_ID}" ]] || fail "--apple-team-id is required"
[[ "${REMOTE_DIR}" != *[[:space:]]* ]] || fail "--remote-dir cannot contain whitespace"

for cmd in ssh rsync; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found in PATH: ${cmd}"
done

if [[ "${REMOTE_DIR}" == "~/"* ]]; then
  REMOTE_HOME="$(ssh "${MAC_HOST}" 'printf %s "$HOME"')"
  REMOTE_DIR="${REMOTE_HOME}/${REMOTE_DIR#~/}"
fi

printf -v REMOTE_DIR_ESCAPED '%q' "${REMOTE_DIR}"
ssh "${MAC_HOST}" "mkdir -p ${REMOTE_DIR_ESCAPED}"

RSYNC_ARGS=(
  -az
  --exclude '.git/'
  --exclude '.venv/'
  --exclude 'node_modules/'
  --exclude 'web/node_modules/'
  --exclude 'web/dist/'
  --exclude 'web/android/'
  --exclude 'web/ios/'
  --exclude '.npm-cache/'
  --exclude '.pytest_cache/'
)
if ((RSYNC_DELETE == 1)); then
  RSYNC_ARGS+=(--delete)
fi

rsync "${RSYNC_ARGS[@]}" "${REPO_ROOT}/" "${MAC_HOST}:${REMOTE_DIR}/"

remote_args=(
  --app-id "${APP_ID}"
  --app-name "${APP_NAME}"
  --device-udid "${DEVICE_UDID}"
  --apple-team-id "${APPLE_TEAM_ID}"
  --scheme "${SCHEME}"
  --configuration "${CONFIGURATION}"
)
if [[ -n "${SERVER_URL}" ]]; then
  remote_args+=(--server-url "${SERVER_URL}")
fi
if ((SKIP_INSTALL == 1)); then
  remote_args+=(--skip-install)
fi

printf -v REMOTE_ARGS_ESCAPED '%q ' "${remote_args[@]}"
ssh "${MAC_HOST}" "cd ${REMOTE_DIR_ESCAPED} && bash tools/mobile/deploy_ios_on_macos.sh ${REMOTE_ARGS_ESCAPED}"

echo "Remote iOS deploy completed via ${MAC_HOST}"
