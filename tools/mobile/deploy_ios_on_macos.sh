#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

APP_ID="com.agenthub.mobile"
APP_NAME="Agent Hub"
SERVER_URL=""
DEVICE_UDID=""
APPLE_TEAM_ID=""
SCHEME="App"
CONFIGURATION="Debug"
SKIP_INSTALL=0

usage() {
  cat <<'USAGE'
Usage: tools/mobile/deploy_ios_on_macos.sh [options]

Options:
  --server-url <url>      Hosted Agent Hub URL for the WebView (example: http://192.168.1.20:8765)
  --app-id <id>           iOS bundle identifier (default: com.agenthub.mobile)
  --app-name <name>       App display name (default: Agent Hub)
  --device-udid <udid>    Physical iPhone UDID (required)
  --apple-team-id <id>    Apple Developer Team ID for signing (required)
  --scheme <name>         Xcode scheme (default: App)
  --configuration <name>  Build configuration (default: Debug)
  --skip-install          Skip "yarn install"
  -h, --help              Show help

Example:
  tools/mobile/deploy_ios_on_macos.sh \
    --server-url http://192.168.1.20:8765 \
    --device-udid 00008110-001234567890801E \
    --apple-team-id ABCD123456
USAGE
}

fail() {
  echo "error: $*" >&2
  exit 1
}

enable_ios_cleartext_if_needed() {
  local plist_path="$1"
  local server_url="$2"

  if [[ "${server_url}" != http://* ]]; then
    /usr/libexec/PlistBuddy -c "Delete :NSAppTransportSecurity:NSAllowsArbitraryLoads" "${plist_path}" >/dev/null 2>&1 || true
    return
  fi

  /usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity dict" "${plist_path}" >/dev/null 2>&1 || true
  /usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity:NSAllowsArbitraryLoads bool true" "${plist_path}" >/dev/null 2>&1 \
    || /usr/libexec/PlistBuddy -c "Set :NSAppTransportSecurity:NSAllowsArbitraryLoads true" "${plist_path}" >/dev/null
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "$(uname -s)" == "Darwin" ]] || fail "this script must run on macOS"
[[ -n "${DEVICE_UDID}" ]] || fail "--device-udid is required"
[[ -n "${APPLE_TEAM_ID}" ]] || fail "--apple-team-id is required"

for cmd in node corepack pod xcodebuild xcrun; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found in PATH: ${cmd}"
done

if ! xcrun xctrace list devices | grep -Fq "${DEVICE_UDID}"; then
  fail "iOS device ${DEVICE_UDID} not found in xcode device list"
fi

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

corepack yarn build

if [[ ! -d "${REPO_ROOT}/web/ios" ]]; then
  corepack yarn cap:add:ios
fi

corepack yarn cap sync ios

IOS_INFO_PLIST="${REPO_ROOT}/web/ios/App/App/Info.plist"
[[ -f "${IOS_INFO_PLIST}" ]] || fail "missing iOS Info.plist at ${IOS_INFO_PLIST}"
enable_ios_cleartext_if_needed "${IOS_INFO_PLIST}" "${SERVER_URL}"

IOS_PROJECT_DIR="${REPO_ROOT}/web/ios/App"
DERIVED_DATA_PATH="${REPO_ROOT}/web/ios/build"
APP_OUTPUT_PATH="${DERIVED_DATA_PATH}/Build/Products/${CONFIGURATION}-iphoneos/App.app"

pushd "${IOS_PROJECT_DIR}" >/dev/null
xcodebuild \
  -workspace App.xcworkspace \
  -scheme "${SCHEME}" \
  -configuration "${CONFIGURATION}" \
  -destination "id=${DEVICE_UDID}" \
  -derivedDataPath "${DERIVED_DATA_PATH}" \
  DEVELOPMENT_TEAM="${APPLE_TEAM_ID}" \
  PRODUCT_BUNDLE_IDENTIFIER="${APP_ID}" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  build
popd >/dev/null

[[ -d "${APP_OUTPUT_PATH}" ]] || fail "compiled app not found at ${APP_OUTPUT_PATH}"

if xcrun devicectl --help >/dev/null 2>&1; then
  xcrun devicectl device install app --device "${DEVICE_UDID}" "${APP_OUTPUT_PATH}"
  xcrun devicectl device process launch --device "${DEVICE_UDID}" "${APP_ID}" || true
elif command -v ios-deploy >/dev/null 2>&1; then
  ios-deploy --id "${DEVICE_UDID}" --bundle "${APP_OUTPUT_PATH}" --justlaunch
else
  fail "neither xcrun devicectl nor ios-deploy are available for app installation"
fi

popd >/dev/null

echo "iOS deploy completed for device ${DEVICE_UDID}"
