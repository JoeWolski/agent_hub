#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

WEB_DIR_NAME="dist"
APP_ID="com.agenthub.mobile"
APP_NAME="Agent Hub"
SERVER_URL=""
CONFIG_PATH="${REPO_ROOT}/web/capacitor.config.json"

usage() {
  cat <<'USAGE'
Usage: tools/mobile/configure_capacitor.sh [options]

Options:
  --app-id <id>          Capacitor app ID/bundle ID (default: com.agenthub.mobile)
  --app-name <name>      App display name (default: Agent Hub)
  --web-dir <dir>        Capacitor webDir (default: dist)
  --server-url <url>     Hosted web app URL (example: http://192.168.1.20:8765)
  --config-path <path>   Output config path (default: web/capacitor.config.json)
  -h, --help             Show help

Notes:
  - When --server-url is set, Capacitor will load the hosted Agent Hub UI instead of bundled files.
  - HTTP URLs set "server.cleartext=true" for development usage.
USAGE
}

fail() {
  echo "error: $*" >&2
  exit 1
}

while (($# > 0)); do
  case "$1" in
    --app-id)
      APP_ID="${2:-}"
      shift 2
      ;;
    --app-name)
      APP_NAME="${2:-}"
      shift 2
      ;;
    --web-dir)
      WEB_DIR_NAME="${2:-}"
      shift 2
      ;;
    --server-url)
      SERVER_URL="${2:-}"
      shift 2
      ;;
    --config-path)
      CONFIG_PATH="${2:-}"
      shift 2
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

[[ -n "${APP_ID}" ]] || fail "--app-id cannot be empty"
[[ -n "${APP_NAME}" ]] || fail "--app-name cannot be empty"
[[ -n "${WEB_DIR_NAME}" ]] || fail "--web-dir cannot be empty"

if [[ ! "${APP_ID}" =~ ^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$ ]]; then
  fail "--app-id must be a reverse-DNS style identifier (example: com.example.app)"
fi

if [[ -n "${SERVER_URL}" && ! "${SERVER_URL}" =~ ^https?://[^[:space:]]+$ ]]; then
  fail "--server-url must be an absolute http(s) URL"
fi

mkdir -p "$(dirname "${CONFIG_PATH}")"

APP_ID="${APP_ID}" \
APP_NAME="${APP_NAME}" \
WEB_DIR_NAME="${WEB_DIR_NAME}" \
SERVER_URL="${SERVER_URL}" \
CONFIG_PATH="${CONFIG_PATH}" \
node <<'NODE'
const fs = require("node:fs");

const appId = process.env.APP_ID;
const appName = process.env.APP_NAME;
const webDir = process.env.WEB_DIR_NAME;
const serverUrl = (process.env.SERVER_URL || "").trim();
const configPath = process.env.CONFIG_PATH;

const config = {
  appId,
  appName,
  webDir,
  bundledWebRuntime: false
};

if (serverUrl) {
  config.server = {
    url: serverUrl,
    cleartext: serverUrl.startsWith("http://")
  };
}

fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
NODE

echo "Wrote ${CONFIG_PATH}"
if [[ -n "${SERVER_URL}" ]]; then
  echo "Configured hosted mode with server URL: ${SERVER_URL}"
else
  echo "Configured bundled mode (no server URL override)."
fi
