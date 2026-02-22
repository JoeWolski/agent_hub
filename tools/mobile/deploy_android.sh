#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

APP_ID="com.agenthub.mobile"
APP_NAME="Agent Hub"
SERVER_URL=""
DEVICE_ID=""
SKIP_INSTALL=0
SKIP_BUILD=0
LAUNCH_AFTER_INSTALL=1
GRADLE_TASK="installDebug"

usage() {
  cat <<'USAGE'
Usage: tools/mobile/deploy_android.sh [options]

Options:
  --server-url <url>      Hosted Agent Hub URL for the WebView (example: http://192.168.1.20:8765)
  --app-id <id>           Android package ID (default: com.agenthub.mobile)
  --app-name <name>       App display name (default: Agent Hub)
  --device-id <serial>    adb device serial to deploy to
  --gradle-task <task>    Gradle task to run (default: installDebug)
  --skip-install          Skip "yarn install"
  --skip-build            Skip frontend build
  --no-launch             Do not launch app after install
  -h, --help              Show help

Examples:
  tools/mobile/deploy_android.sh --server-url http://192.168.1.20:8765
  tools/mobile/deploy_android.sh --server-url http://192.168.1.20:8765 --device-id R3CX1234ABC
USAGE
}

fail() {
  echo "error: $*" >&2
  exit 1
}

while (($# > 0)); do
  case "$1" in
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
    --device-id)
      DEVICE_ID="${2:-}"
      shift 2
      ;;
    --gradle-task)
      GRADLE_TASK="${2:-}"
      shift 2
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --no-launch)
      LAUNCH_AFTER_INSTALL=0
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

for cmd in node corepack adb java; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found in PATH: ${cmd}"
done

adb start-server >/dev/null
mapfile -t CONNECTED_DEVICES < <(adb devices | awk 'NR > 1 && $2 == "device" { print $1 }')

if ((${#CONNECTED_DEVICES[@]} == 0)); then
  fail "no Android devices detected (enable USB debugging and confirm adb authorization)"
fi

if [[ -z "${DEVICE_ID}" ]]; then
  if ((${#CONNECTED_DEVICES[@]} > 1)); then
    printf 'Connected devices:\n%s\n' "${CONNECTED_DEVICES[@]}" >&2
    fail "multiple devices connected; pass --device-id"
  fi
  DEVICE_ID="${CONNECTED_DEVICES[0]}"
fi

if ! printf '%s\n' "${CONNECTED_DEVICES[@]}" | grep -Fxq "${DEVICE_ID}"; then
  printf 'Connected devices:\n%s\n' "${CONNECTED_DEVICES[@]}" >&2
  fail "--device-id ${DEVICE_ID} is not currently connected"
fi

export ANDROID_SERIAL="${DEVICE_ID}"
export NPM_CONFIG_CACHE="${REPO_ROOT}/.npm-cache"

configure_args=(
  --app-id "${APP_ID}"
  --app-name "${APP_NAME}"
)
if [[ -n "${SERVER_URL}" ]]; then
  configure_args+=(--server-url "${SERVER_URL}")
fi
"${SCRIPT_DIR}/configure_capacitor.sh" "${configure_args[@]}"

pushd "${REPO_ROOT}/web" >/dev/null

if ((SKIP_INSTALL == 0)); then
  corepack yarn install --frozen-lockfile
fi

if ((SKIP_BUILD == 0)); then
  corepack yarn build
fi

if [[ ! -d "${REPO_ROOT}/web/android" ]]; then
  corepack yarn cap:add:android
fi

corepack yarn cap sync android

pushd "${REPO_ROOT}/web/android" >/dev/null
./gradlew --no-daemon "${GRADLE_TASK}"
popd >/dev/null

if ((LAUNCH_AFTER_INSTALL == 1)); then
  adb -s "${DEVICE_ID}" shell monkey -p "${APP_ID}" -c android.intent.category.LAUNCHER 1 >/dev/null
fi

popd >/dev/null

echo "Android deploy completed for device ${DEVICE_ID}"
