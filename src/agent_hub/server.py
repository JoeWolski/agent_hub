from __future__ import annotations

import asyncio
import base64
import copy
import fcntl
import hashlib
import html
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import pwd
import queue
import re
import secrets
import signal
import socket
import struct
import subprocess
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from string import Template
from threading import Lock, Thread, current_thread
from typing import Any, Callable

import click
from agent_cli import cli as agent_cli_image
import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocketDisconnect
from fastapi.responses import JSONResponse

from agent_core import (
    AgentRuntimeConfig,
    ConfigError,
    CredentialResolutionError,
    DEFAULT_RUNTIME_RUN_MODE,
    IdentityError,
    MountVisibilityError,
    NetworkReachabilityError,
    load_agent_runtime_config,
)
from agent_core.errors import TypedAgentError, typed_error_payload
from agent_core import identity as core_identity
from agent_core import launch as core_launch
from agent_core import logging as core_logging
from agent_core import paths as core_paths
from agent_core import shared as core_shared
from agent_hub.api import register_hub_routes
from agent_hub.domains import (
    AuthDomain,
    AutoConfigDomain,
    ChatRuntimeDomain,
    CredentialsDomain,
    ProjectDomain,
    RuntimeDomain,
)
from agent_hub.services.artifacts_service import ArtifactsService
from agent_hub.services.auth_service import AuthService
from agent_hub.services.auto_config_service import AutoConfigService
from agent_hub.services.app_state_service import AppStateService
from agent_hub.services.chat_service import ChatService
from agent_hub.services.credentials_service import CredentialsService
from agent_hub.services.event_service import EventService
from agent_hub.services.lifecycle_service import LifecycleService
from agent_hub.services.project_service import ProjectService
from agent_hub.services.runtime_service import RuntimeService
from agent_hub.services.settings_service import SettingsService
from agent_hub.integrations import run_command
from agent_hub.store import HubStateStore


STATE_FILE_NAME = "state.json"
AGENT_CAPABILITIES_CACHE_FILE_NAME = "agent_capabilities_cache.json"
SECRETS_DIR_NAME = "secrets"
OPENAI_CREDENTIALS_FILE_NAME = "openai.env"
OPENAI_CODEX_AUTH_FILE_NAME = "auth.json"
GITHUB_APP_INSTALLATION_FILE_NAME = "github_app_installation.json"
GITHUB_TOKENS_FILE_NAME = "github_tokens.json"
GITLAB_TOKENS_FILE_NAME = "gitlab_tokens.json"
GIT_CREDENTIALS_DIR_NAME = "git_credentials"
CHAT_RUNTIME_CONFIGS_DIR_NAME = "chat_runtime_configs"
GITHUB_APP_SETTINGS_FILE_NAME = "github_app_settings.json"
GITHUB_APP_ID_ENV = "AGENT_HUB_GITHUB_APP_ID"
GITHUB_APP_PRIVATE_KEY_ENV = "AGENT_HUB_GITHUB_APP_PRIVATE_KEY"
GITHUB_APP_PRIVATE_KEY_FILE_ENV = "AGENT_HUB_GITHUB_APP_PRIVATE_KEY_FILE"
GITHUB_APP_SLUG_ENV = "AGENT_HUB_GITHUB_APP_SLUG"
GITHUB_APP_WEB_BASE_URL_ENV = "AGENT_HUB_GITHUB_WEB_BASE_URL"
GITHUB_APP_API_BASE_URL_ENV = "AGENT_HUB_GITHUB_API_BASE_URL"
GITHUB_APP_DEFAULT_WEB_BASE_URL = "https://github.com"
GITHUB_APP_DEFAULT_API_BASE_URL = "https://api.github.com"
SYSTEM_PROMPT_FILE_NAME = "SYSTEM_PROMPT.md"
GITHUB_APP_JWT_LIFETIME_SECONDS = 9 * 60
GITHUB_APP_TOKEN_REFRESH_SKEW_SECONDS = 120
GITHUB_APP_API_TIMEOUT_SECONDS = 8.0
GITHUB_APP_PRIVATE_KEY_MAX_CHARS = 256_000
GITHUB_APP_SETUP_SESSION_LIFETIME_SECONDS = 60 * 60
GITHUB_APP_DEFAULT_NAME = "Agent Hub"
GITHUB_CONNECTION_MODE_GITHUB_APP = "github_app"
GIT_CONNECTION_MODE_PERSONAL_ACCESS_TOKEN = "personal_access_token"
PROJECT_CREDENTIAL_BINDING_MODE_AUTO = "auto"
PROJECT_CREDENTIAL_BINDING_MODE_SET = "set"
PROJECT_CREDENTIAL_BINDING_MODE_SINGLE = "single"
PROJECT_CREDENTIAL_BINDING_MODE_ALL = "all"
PROJECT_CREDENTIAL_BINDING_MODES = {
    PROJECT_CREDENTIAL_BINDING_MODE_AUTO,
    PROJECT_CREDENTIAL_BINDING_MODE_SET,
    PROJECT_CREDENTIAL_BINDING_MODE_SINGLE,
    PROJECT_CREDENTIAL_BINDING_MODE_ALL,
}
GITHUB_PERSONAL_ACCESS_TOKEN_MIN_CHARS = 20
GITHUB_PERSONAL_ACCESS_TOKEN_ID_MAX_CHARS = 120
GIT_CREDENTIAL_DEFAULT_SCHEME = "https"
GIT_CREDENTIAL_ALLOWED_SCHEMES = {"http", "https"}
GIT_PROVIDER_GITHUB = "github"
GIT_PROVIDER_GITLAB = "gitlab"
GITLAB_PERSONAL_ACCESS_TOKEN_REQUIRED_SCOPES = frozenset({"read_repository", "write_repository"})
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_CONTAINER_HOME = "/workspace"
DEFAULT_CONTAINER_TMP_DIR = f"{DEFAULT_CONTAINER_HOME}/tmp"
RUNTIME_TMP_ROOT_DIR_NAME = "tmp"
RUNTIME_TMP_PROJECTS_DIR_NAME = "projects"
RUNTIME_TMP_CHATS_DIR_NAME = "chats"
RUNTIME_TMP_WORKSPACE_DIR_NAME = "workspace"
AGENT_HUB_TMP_HOST_PATH_ENV = "AGENT_HUB_TMP_HOST_PATH"
AGENT_HUB_HOST_UID_ENV = "AGENT_HUB_HOST_UID"
AGENT_HUB_HOST_GID_ENV = "AGENT_HUB_HOST_GID"
AGENT_HUB_HOST_SUPP_GIDS_ENV = "AGENT_HUB_HOST_SUPPLEMENTARY_GIDS"
AGENT_HUB_SHARED_ROOT_ENV = "AGENT_HUB_SHARED_ROOT"
AGENT_HUB_HOST_USER_ENV = "AGENT_HUB_HOST_USER"
AGENT_TOOLS_MCP_RUNTIME_DIR_NAME = "agent_hub"
AGENT_TOOLS_MCP_RUNTIME_FILE_NAME = "agent_tools_mcp.py"
AGENT_TOOLS_URL_ENV = "AGENT_HUB_AGENT_TOOLS_URL"
AGENT_TOOLS_TOKEN_ENV = "AGENT_HUB_AGENT_TOOLS_TOKEN"
AGENT_TOOLS_PROJECT_ID_ENV = "AGENT_HUB_AGENT_TOOLS_PROJECT_ID"
AGENT_TOOLS_CHAT_ID_ENV = "AGENT_HUB_AGENT_TOOLS_CHAT_ID"
AGENT_TOOLS_READY_ACK_GUID_ENV = "AGENT_HUB_READY_ACK_GUID"
AGENT_TOOLS_MCP_CONTAINER_SCRIPT_PATH = str(
    PurePosixPath(DEFAULT_CONTAINER_HOME)
    / ".codex"
    / AGENT_TOOLS_MCP_RUNTIME_DIR_NAME
    / AGENT_TOOLS_MCP_RUNTIME_FILE_NAME
)
TMP_DIR_TMPFS_SPEC = "/tmp:mode=1777,exec"
DEFAULT_ARTIFACT_PUBLISH_HOST = "host.docker.internal"
TERMINAL_QUEUE_MAX = 256
HUB_EVENT_QUEUE_MAX = 512
OPENAI_ACCOUNT_LOGIN_LOG_MAX_CHARS = 16_000
OPENAI_ACCOUNT_LOGIN_DEFAULT_CALLBACK_PORT = 1455
OPENAI_ACCOUNT_CALLBACK_FORWARD_TIMEOUT_SECONDS = 8.0
OPENAI_ACCOUNT_CALLBACK_DOCKER_INSPECT_TIMEOUT_SECONDS = 2.0
OPENAI_ACCOUNT_CALLBACK_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "code",
        "code_verifier",
        "id_token",
        "refresh_token",
        "state",
        "token",
    }
)
DEFAULT_AGENT_IMAGE = "agent-ubuntu2204-codex:latest"
AGENT_TYPE_CODEX = "codex"
AGENT_TYPE_CLAUDE = "claude"
AGENT_TYPE_GEMINI = "gemini"
DEFAULT_CHAT_AGENT_TYPE = AGENT_TYPE_CODEX
DEFAULT_CLAUDE_MODEL = "opus"
SUPPORTED_CHAT_AGENT_TYPES = {AGENT_TYPE_CODEX, AGENT_TYPE_CLAUDE, AGENT_TYPE_GEMINI}
CHAT_LAYOUT_ENGINE_CLASSIC = "classic"
CHAT_LAYOUT_ENGINE_FLEXLAYOUT = "flexlayout"
DEFAULT_CHAT_LAYOUT_ENGINE = CHAT_LAYOUT_ENGINE_FLEXLAYOUT
SUPPORTED_CHAT_LAYOUT_ENGINES = {CHAT_LAYOUT_ENGINE_CLASSIC, CHAT_LAYOUT_ENGINE_FLEXLAYOUT}
AGENT_COMMAND_BY_TYPE = {
    AGENT_TYPE_CODEX: "codex",
    AGENT_TYPE_CLAUDE: "claude",
    AGENT_TYPE_GEMINI: "gemini",
}
AGENT_RESUME_ARGS_BY_TYPE = {
    AGENT_TYPE_CLAUDE: ("--continue",),
    AGENT_TYPE_GEMINI: ("--resume",),
}
AGENT_LABEL_BY_TYPE = {
    AGENT_TYPE_CODEX: "Codex",
    AGENT_TYPE_CLAUDE: "Claude",
    AGENT_TYPE_GEMINI: "Gemini CLI",
}


def _agent_command_for_type(agent_type: str) -> str:
    normalized = str(agent_type or "").strip().lower()
    command = AGENT_COMMAND_BY_TYPE.get(normalized)
    if command is None:
        supported = ", ".join(sorted(AGENT_COMMAND_BY_TYPE.keys()))
        raise HTTPException(status_code=400, detail=f"agent_type must be one of: {supported}.")
    return command
AGENT_CAPABILITY_DEFAULT_MODELS_BY_TYPE = {
    AGENT_TYPE_CODEX: ["default"],
    AGENT_TYPE_CLAUDE: ["default"],
    AGENT_TYPE_GEMINI: ["default"],
}
AGENT_CAPABILITY_DEFAULT_REASONING_BY_TYPE = {
    AGENT_TYPE_CODEX: ["default"],
    AGENT_TYPE_CLAUDE: ["default"],
    AGENT_TYPE_GEMINI: ["default"],
}
AGENT_CAPABILITY_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,120}")
AGENT_CAPABILITY_CODEX_MODEL_TOKEN_RE = re.compile(r"^(?:gpt-[a-z0-9][a-z0-9._-]*|o[0-9][a-z0-9._-]*)$")
AGENT_CAPABILITY_GEMINI_MODEL_ALIASES = {"auto", "pro", "flash", "flash-lite"}
AGENT_CAPABILITY_GEMINI_FALLBACK_MODELS = (
    "auto",
    "pro",
    "flash",
    "flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
AGENT_CAPABILITY_REASONING_LEVELS_BY_TYPE = {
    AGENT_TYPE_CODEX: ("minimal", "low", "medium", "high", "xhigh"),
    AGENT_TYPE_CLAUDE: ("low", "medium", "high", "max"),
    AGENT_TYPE_GEMINI: ("low", "medium", "high", "max"),
}
AGENT_CAPABILITY_REASONING_VALUE_RE = re.compile(r"\b(?:minimal|low|medium|high|xhigh|max)\b")
AGENT_CAPABILITY_REASONING_EXPECTED_VALUES_RE = re.compile(
    r"\bexpected\s+one\s+of\b\s+([^\n\r]+)",
    re.IGNORECASE,
)
AGENT_CAPABILITY_REASONING_LIST_RE = re.compile(
    r"(?:\b(?:reasoning|effort|thinking)(?:\s+(?:mode|modes|level|levels|effort))?\b[^:\n\r]{0,48})"
    r"(?:\b(?:possible values?|choices?|available values?|valid values?)\b)?[ \t]*[:=-][ \t]*([^\n\r]+)",
    re.IGNORECASE,
)
AGENT_CAPABILITY_MODEL_LIST_RE = re.compile(
    r"(?:\bmodel(?:\s+aliases?)?\b[^:\n\r]{0,48})"
    r"(?:\b(?:possible values?|choices?|available values?|valid values?)\b)?[ \t]*[:=-][ \t]*([^\n\r]+)",
    re.IGNORECASE,
)
AGENT_CAPABILITY_HELP_OPTION_RE = re.compile(r"(?<!\w)--([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
AGENT_CAPABILITY_HELP_LIST_MARKER_RE = re.compile(
    r"\b(?:possible values?|choices?|available values?|valid values?)\b", re.IGNORECASE
)
AGENT_CAPABILITY_HELP_LIST_VALUE_RE = re.compile(
    r"\b(?:possible values?|choices?|available values?|valid values?)\b\s*[:=-]\s*([^\n\r]+)",
    re.IGNORECASE,
)
AGENT_CAPABILITY_HELP_INLINE_VALUES_RE = re.compile(
    r"\[\s*possible values?\s*:\s*([^\]]+)\]", re.IGNORECASE
)
AGENT_CAPABILITY_HELP_BULLET_VALUE_RE = re.compile(r"^\s*-\s*([A-Za-z0-9][A-Za-z0-9._-]{0,80})\b")
AGENT_CAPABILITY_HELP_NUMBERED_VALUE_RE = re.compile(
    r"^\s*(?:[>›]\s*)?(?:\d+[.)]\s+)([A-Za-z0-9][A-Za-z0-9._-]{0,80})\b"
)
AGENT_CAPABILITY_HELP_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,80}")
AGENT_CAPABILITY_DISCOVERY_TIMEOUT_SECONDS = float(
    os.environ.get("AGENT_HUB_AGENT_CAPABILITY_DISCOVERY_TIMEOUT_SECONDS", "8.0")
)
AGENT_CAPABILITY_CODEX_MODELS_DOC_URL = "https://developers.openai.com/codex/models"
AGENT_CAPABILITY_CODEX_MODELS_DOC_NAME_RE = re.compile(
    r'\bname"\s*:\s*\[0,\s*"([a-z0-9][a-z0-9.-]*(?:-[a-z0-9][a-z0-9.-]*)*)"\]',
    re.IGNORECASE,
)
AGENT_CAPABILITY_CODEX_MODELS_DOC_MODEL_RE = re.compile(
    r"\bcodex\s+-m\s+([a-z0-9][a-z0-9.-]*(?:-[a-z0-9][a-z0-9.-]*)*)\b",
    re.IGNORECASE,
)
AGENT_CAPABILITY_CODEX_REASONING_FALLBACK_COMMAND = (
    "codex",
    "exec",
    "-c",
    'model_reasoning_effort="__agent_hub_invalid_reasoning__"',
    "capability-probe",
)
AGENT_CAPABILITY_DISCOVERY_COMMANDS_BY_TYPE = {
    AGENT_TYPE_CODEX: (
        ("codex", "--help"),
    ),
    AGENT_TYPE_CLAUDE: (
        ("claude", "--help"),
    ),
    AGENT_TYPE_GEMINI: (
        ("gemini", "--help"),
    ),
}
DEFAULT_PTY_COLS = 160
DEFAULT_PTY_ROWS = 48
CHAT_PREVIEW_LOG_MAX_BYTES = 150_000
CHAT_TITLE_MAX_CHARS = 80
CHAT_SUBTITLE_MAX_CHARS = 240
CHAT_SUBTITLE_MARKERS = (".", "•", "◦", "∙", "·", "●", "○", "▪", "▫", "‣", "⁃")
CHAT_DEFAULT_NAME = "New Chat"
CHAT_AUTOGENERATED_NAME_RE = re.compile(r"^chat-[0-9a-f]{8}$", re.IGNORECASE)
CHAT_STATUS_STARTING = "starting"
CHAT_STATUS_RUNNING = "running"
CHAT_STATUS_STOPPED = "stopped"
CHAT_STATUS_FAILED = "failed"
CHAT_STATUS_REASON_CHAT_CREATED = "chat_created"
CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED = "chat_close_requested"
CHAT_STATUS_REASON_USER_CLOSED_TAB = "user_closed_tab"
CHAT_STATUS_REASON_STARTUP_RECONCILE_ORPHAN_PROCESS = "startup_reconcile_orphan_process"
CHAT_STATUS_REASON_STARTUP_RECONCILE_PROCESS_MISSING = "startup_reconcile_process_missing"
SUPPORTED_CHAT_STATUSES = {
    CHAT_STATUS_STARTING,
    CHAT_STATUS_RUNNING,
    CHAT_STATUS_STOPPED,
    CHAT_STATUS_FAILED,
}
STARTUP_STALE_DOCKER_CONTAINER_PREFIXES = ("agent-setup-", "agent-hub-openai-login-")
CHAT_TITLE_API_TIMEOUT_SECONDS = 8.0
CHAT_TITLE_CODEX_TIMEOUT_SECONDS = 25.0
CHAT_TITLE_OPENAI_MODEL = os.environ.get("AGENT_HUB_CHAT_TITLE_MODEL", "gpt-4.1-mini")
CHAT_TITLE_ACCOUNT_MODEL = "chatgpt-account"
CHAT_TITLE_AUTH_MODE_ACCOUNT = "chatgpt_account"
CHAT_TITLE_AUTH_MODE_API_KEY = "api_key"
CHAT_TITLE_AUTH_MODE_NONE = "none"
CHAT_TITLE_NO_CREDENTIALS_ERROR = (
    "No OpenAI credentials configured for chat title generation. Connect an OpenAI account or API key in Settings."
)
CHAT_ARTIFACTS_MAX_ITEMS = 200
CHAT_ARTIFACT_PROMPT_HISTORY_MAX_ITEMS = 64
CHAT_ARTIFACT_PROMPT_LABEL_MAX_CHARS = 2000
CHAT_ARTIFACT_NAME_MAX_CHARS = 180
CHAT_ARTIFACT_PATH_MAX_CHARS = 1024
AUTO_CONFIG_CHAT_TIMEOUT_SECONDS = float(os.environ.get("AGENT_HUB_AUTO_CONFIG_TIMEOUT_SECONDS", "240"))
AUTO_CONFIG_MODEL = "chatgpt-account-codex"
AUTO_CONFIG_NOT_CONNECTED_ERROR = (
    "Auto configure needs a connected ChatGPT account in Settings to run a temporary repository analysis chat."
)
AUTO_CONFIG_CANCELLED_ERROR = "Auto-configure was cancelled by user."
AUTO_CONFIG_MISSING_OUTPUT_ERROR = "Temporary auto-config chat did not return a JSON recommendation."
AUTO_CONFIG_INVALID_OUTPUT_ERROR = "Temporary auto-config chat returned invalid JSON."
PROJECT_BUILD_CANCELLED_ERROR = "Project build was cancelled by user."
AUTO_CONFIG_NOTES_MAX_CHARS = 400
AUTO_CONFIG_REPO_DOCKERFILE_MIN_SCORE = 70
AUTO_CONFIG_REQUEST_ID_MAX_CHARS = 120
AUTO_CONFIG_CACHE_SIGNAL_MAX_FILES = 3000
AUTO_CONFIG_CACHE_SIGNAL_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "out",
    "target",
}
AUTO_CONFIG_CACHE_SIGNAL_IGNORED_PATH_PARTS = {
    "test",
    "tests",
    "__tests__",
    "testing",
    "spec",
    "specs",
    "fixture",
    "fixtures",
}
AUTO_CONFIG_CACHE_SIGNAL_DOC_DIRS = {"docs", "doc", "documentation"}
AUTO_CONFIG_CACHE_SIGNAL_FILENAMES = {
    "cmakelists.txt",
    "meson.build",
    "meson.options",
    "makefile",
    "gnu makefile",
    "build.bazel",
    "workspace",
    ".bazelrc",
    "cargo.toml",
    "cargo.config",
    "config.toml",
    "dockerfile",
    "sconstruct",
    "sconscript",
}
SNAPSHOT_AGENT_CLI_RUNTIME_INPUT_FILES = (
    "docker/agent_cli/Dockerfile",
    "docker/agent_cli/Dockerfile.base",
    "docker/agent_hub/Dockerfile",
    "docker/development/Dockerfile",
    "docker/agent_cli/docker-entrypoint.py",
    "src/agent_hub/agent_tools_mcp.py",
    "src/agent_cli/cli.py",
    "src/agent_cli/providers.py",
)
ARTIFACT_STORAGE_DIR_NAME = "artifacts"
ARTIFACT_STORAGE_CHAT_DIR_NAME = "chats"
ARTIFACT_STORAGE_SESSION_DIR_NAME = "agent_tools_sessions"
AUTO_CONFIG_CACHE_SIGNAL_SUFFIXES = {
    ".cmake",
    ".mk",
    ".ninja",
    ".bazel",
    ".bzl",
    ".toml",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".conf",
    ".ini",
}
AUTO_CONFIG_CCACHE_SIGNAL_PATTERNS = (
    re.compile(r"\bCMAKE_[A-Z0-9_]*COMPILER_LAUNCHER\b[^\n#]*\bccache\b", re.IGNORECASE),
    re.compile(
        r"(?:^|[;&|]\s*)(?:[A-Za-z0-9_./-]+/)?ccache\s+(?:--|[A-Za-z0-9_./-])",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"\b(?:export\s+)?CCACHE_[A-Z0-9_]+\s*(?:=|:)"),
    re.compile(r"\b(?:export\s+)?(?:CC|CXX)\s*=\s*(?:\"|')?ccache\b", re.IGNORECASE),
)
AUTO_CONFIG_SCCACHE_SIGNAL_PATTERNS = (
    re.compile(r"\bCMAKE_[A-Z0-9_]*COMPILER_LAUNCHER\b[^\n#]*\bsccache\b", re.IGNORECASE),
    re.compile(
        r"(?:^|[;&|]\s*)(?:[A-Za-z0-9_./-]+/)?sccache\s+(?:--|[A-Za-z0-9_./-])",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"\b(?:export\s+)?SCCACHE_[A-Z0-9_]+\s*(?:=|:)"),
    re.compile(r"\bRUSTC_WRAPPER\s*=\s*(?:\"|')?sccache\b", re.IGNORECASE),
)
AUTO_CONFIG_SETUP_CHAIN_SPLIT_RE = re.compile(r"\s*&&\s*")
AUTO_CONFIG_SETUP_CD_RE = re.compile(r"^cd\s+([^\s;&|]+)$", re.IGNORECASE)
AUTO_CONFIG_SETUP_CWD_RE = re.compile(
    r"(?:^|\s)--cwd\s+([^\s\"']+|\"[^\"]+\"|'[^']+')",
    re.IGNORECASE,
)
AUTO_CONFIG_SETUP_PREFIX_RE = re.compile(
    r"(?:^|\s)--prefix\s+([^\s\"']+|\"[^\"]+\"|'[^']+')",
    re.IGNORECASE,
)
AUTO_CONFIG_SETUP_UV_SYNC_RE = re.compile(r"^uv\s+sync\b", re.IGNORECASE)
AUTO_CONFIG_SETUP_YARN_INSTALL_RE = re.compile(r"^(?:corepack\s+)?yarn\s+install\b", re.IGNORECASE)
AUTO_CONFIG_SETUP_NPM_CI_RE = re.compile(r"^npm\s+ci\b", re.IGNORECASE)
AUTO_CONFIG_DOCKER_SOCKET_PATHS = {"/var/run/docker.sock", "/run/docker.sock"}
PROMPTS_DIR_NAME = "prompts"
PROMPT_CHAT_TITLE_OPENAI_SYSTEM_FILE = "chat_title_openai_system.md"
PROMPT_CHAT_TITLE_OPENAI_USER_FILE = "chat_title_openai_user.md"
PROMPT_CHAT_TITLE_CODEX_REQUEST_FILE = "chat_title_codex_request.md"
PROMPT_AUTO_CONFIGURE_PROJECT_FILE = "auto_configure_project.md"
ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:"
    r"[@-Z\\-_]"
    r"|\[[0-?]*[ -/]*[@-~]"
    r"|\][^\x1B\x07]*(?:\x07|\x1B\\)"
    r"|P[^\x1B\x07]*(?:\x07|\x1B\\)"
    r")"
)
TERMINAL_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
LEADING_INVISIBLE_RE = re.compile(r"^[\u200b\u200c\u200d\u2060\ufeff\u200e\u200f]+")
ANSI_CURSOR_POSITION_RE = re.compile(r"\x1b\[[0-9;?]*[Hf]")
ANSI_ERASE_IN_LINE_RE = re.compile(r"\x1b\[[0-9;?]*K")
OSC_COLOR_RESPONSE_FRAGMENT_RE = re.compile(
    r"(?:^|\s)\]?\d{1,3};(?:rgb|rgba):[0-9a-f]{2,4}/[0-9a-f]{2,4}/[0-9a-f]{2,4}",
    re.IGNORECASE,
)
RESERVED_ENV_VAR_KEYS = {
    "OPENAI_API_KEY",
    "AGENT_HUB_GIT_USER_NAME",
    "AGENT_HUB_GIT_USER_EMAIL",
    AGENT_TOOLS_URL_ENV,
    AGENT_TOOLS_TOKEN_ENV,
    AGENT_TOOLS_PROJECT_ID_ENV,
    AGENT_TOOLS_CHAT_ID_ENV,
    AGENT_TOOLS_READY_ACK_GUID_ENV,
}
AGENT_TOOLS_TOKEN_HEADER = "x-agent-hub-agent-tools-token"
HUB_LOG_LEVEL_CHOICES = ("critical", "error", "warning", "info", "debug")
GITHUB_APP_PRIVATE_KEY_BEGIN_MARKERS = {
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
}
GITHUB_APP_PRIVATE_KEY_END_MARKERS = {
    "-----END RSA PRIVATE KEY-----",
    "-----END PRIVATE KEY-----",
}

EVENT_TYPE_SNAPSHOT = "snapshot"
EVENT_TYPE_STATE_CHANGED = "state_changed"
EVENT_TYPE_AUTH_CHANGED = "auth_changed"
EVENT_TYPE_OPENAI_ACCOUNT_SESSION = "openai_account_session"
EVENT_TYPE_PROJECT_BUILD_LOG = "project_build_log"
EVENT_TYPE_AUTO_CONFIG_LOG = "auto_config_log"
EVENT_TYPE_AGENT_CAPABILITIES_CHANGED = "agent_capabilities_changed"
AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED = "container_bootstrapped"
AGENT_READY_ACK_STAGE_AGENT_PROCESS_STARTED = "agent_process_started"
SUPPORTED_AGENT_READY_ACK_STAGES = {
    AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED,
    AGENT_READY_ACK_STAGE_AGENT_PROCESS_STARTED,
}

LOGGER = logging.getLogger("agent_hub")
LOGGER.addHandler(logging.NullHandler())


@dataclass
class ChatRuntime:
    process: subprocess.Popen
    master_fd: int
    listeners: set[queue.Queue[str | None]] = field(default_factory=set)


@dataclass
class OpenAIAccountLoginSession:
    id: str
    process: subprocess.Popen[str]
    container_name: str
    started_at: str
    method: str = "browser_callback"
    status: str = "starting"
    login_url: str = ""
    device_code: str = ""
    local_callback_url: str = ""
    callback_port: int = OPENAI_ACCOUNT_LOGIN_DEFAULT_CALLBACK_PORT
    callback_path: str = "/auth/callback"
    log_tail: str = ""
    exit_code: int | None = None
    completed_at: str = ""
    error: str = ""


@dataclass
class OpenAICallbackContainerForwardResult:
    attempted: bool = False
    ok: bool = False
    status_code: int = 0
    response_body: str = ""
    error_class: str = ""
    error_detail: str = ""


@dataclass
class AutoConfigRequestState:
    request_id: str
    process: subprocess.Popen[str] | None = None
    cancel_requested: bool = False


@dataclass
class ProjectBuildRequestState:
    project_id: str
    process: subprocess.Popen[str] | None = None
    cancel_requested: bool = False


@dataclass(frozen=True)
class GithubAppSettings:
    app_id: str
    app_slug: str
    private_key: str
    web_base_url: str
    api_base_url: str


@dataclass
class GithubAppSetupSession:
    id: str
    state: str
    status: str
    form_action: str
    manifest: dict[str, Any]
    callback_url: str
    web_base_url: str
    api_base_url: str
    started_at: str
    expires_at: str
    completed_at: str = ""
    error: str = ""
    app_id: str = ""
    app_slug: str = ""


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _agent_cli_runtime_inputs_fingerprint() -> str:
    repo_root = _repo_root()
    fingerprint_items: list[dict[str, str]] = []
    for relative_path in SNAPSHOT_AGENT_CLI_RUNTIME_INPUT_FILES:
        input_path = repo_root / relative_path
        file_hash = "missing"
        if input_path.is_file():
            try:
                file_hash = _sha256_file(input_path)
            except OSError as exc:
                file_hash = f"read-error:{exc.__class__.__name__}"
        fingerprint_items.append({"path": relative_path, "sha256": file_hash})

    payload = json.dumps(fingerprint_items, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent / PROMPTS_DIR_NAME


@lru_cache(maxsize=16)
def _load_prompt_template(prompt_file_name: str) -> str:
    file_name = str(prompt_file_name or "").strip()
    if not file_name:
        raise RuntimeError("Prompt template filename is required.")
    path = _prompts_dir() / file_name
    try:
        template_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Prompt template not found: {path}") from exc
    normalized = template_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise RuntimeError(f"Prompt template is empty: {path}")
    return normalized


def _render_prompt_template(prompt_file_name: str, **values: Any) -> str:
    template = Template(_load_prompt_template(prompt_file_name))
    try:
        return template.substitute({key: str(value) for key, value in values.items()})
    except KeyError as exc:
        placeholder = str(exc.args[0] if exc.args else "")
        raise RuntimeError(
            f"Prompt template '{prompt_file_name}' is missing value for placeholder '{placeholder}'."
        ) from exc


def _default_data_dir() -> Path:
    return core_paths.default_agent_hub_data_dir()


def _default_config_file() -> Path:
    return core_shared.default_config_file(_repo_root(), cwd=Path.cwd())


def _default_system_prompt_file() -> Path:
    return core_shared.default_system_prompt_file(_repo_root(), SYSTEM_PROMPT_FILE_NAME, cwd=Path.cwd())


def _frontend_dist_dir() -> Path:
    return _repo_root() / "web" / "dist"


def _frontend_index_file() -> Path:
    return _frontend_dist_dir() / "index.html"


def _normalize_log_level(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in HUB_LOG_LEVEL_CHOICES:
        return normalized
    return "info"


def _normalize_chat_agent_type(raw_value: Any, *, strict: bool = False) -> str:
    value = str(raw_value or "").strip().lower()
    if value in SUPPORTED_CHAT_AGENT_TYPES:
        return value
    if strict:
        supported = ", ".join(sorted(SUPPORTED_CHAT_AGENT_TYPES))
        raise HTTPException(status_code=400, detail=f"agent_type must be one of: {supported}.")
    return DEFAULT_CHAT_AGENT_TYPE


def _resolve_optional_chat_agent_type(raw_value: Any, *, default_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return _normalize_chat_agent_type(default_value, strict=True)
    return _normalize_chat_agent_type(value, strict=True)


def _normalize_state_chat_agent_type(raw_value: Any, *, chat_id: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ConfigError(f"Invalid chat state for chat '{chat_id}': missing required agent_type.")
    try:
        return _normalize_chat_agent_type(value, strict=True)
    except HTTPException as exc:
        detail = str(exc.detail or "invalid agent_type")
        raise ConfigError(f"Invalid chat state for chat '{chat_id}': {detail}") from exc


def _cli_arg_matches_option(arg: str, *, long_option: str, short_option: str | None = None) -> bool:
    if arg == long_option or arg.startswith(f"{long_option}="):
        return True
    if short_option and (arg == short_option or arg.startswith(f"{short_option}=")):
        return True
    return False


def _has_cli_option(args: list[str], *, long_option: str, short_option: str | None = None) -> bool:
    return any(_cli_arg_matches_option(str(arg), long_option=long_option, short_option=short_option) for arg in args)


def _cli_option_value(args: list[str], *, long_option: str, short_option: str | None = None) -> str:
    values = core_launch.cli_option_values(args, long_option=long_option, short_option=short_option)
    if not values:
        return ""
    return str(values[-1]).strip()


def _cli_option_values(args: list[str], *, long_option: str, short_option: str | None = None) -> list[str]:
    return core_launch.cli_option_values(args, long_option=long_option, short_option=short_option)


def _auto_config_analysis_model(agent_type: str, agent_args: list[str]) -> str:
    selected_model = _cli_option_value(agent_args, long_option="--model", short_option="-m")
    if selected_model and selected_model.lower() != "default":
        return selected_model
    if agent_type == AGENT_TYPE_CODEX:
        return AUTO_CONFIG_MODEL
    return f"{agent_type}-default"


def _strip_explicit_codex_default_model(agent_args: list[str]) -> list[str]:
    normalized_args = [str(arg) for arg in agent_args]
    filtered: list[str] = []
    skip_next = False
    for index, arg in enumerate(normalized_args):
        if skip_next:
            skip_next = False
            continue

        if arg == "--model":
            next_value = str(normalized_args[index + 1]).strip().lower() if index + 1 < len(normalized_args) else ""
            if next_value != "default":
                filtered.append(arg)
                if index + 1 < len(normalized_args):
                    filtered.append(normalized_args[index + 1])
            skip_next = index + 1 < len(normalized_args)
            continue

        if arg.startswith("--model="):
            _, _, value = arg.partition("=")
            if str(value).strip().lower() != "default":
                filtered.append(arg)
            continue

        if arg == "-m":
            next_value = str(normalized_args[index + 1]).strip().lower() if index + 1 < len(normalized_args) else ""
            if next_value != "default":
                filtered.append(arg)
                if index + 1 < len(normalized_args):
                    filtered.append(normalized_args[index + 1])
            skip_next = index + 1 < len(normalized_args)
            continue

        if arg.startswith("-m="):
            _, _, value = arg.partition("=")
            if str(value).strip().lower() != "default":
                filtered.append(arg)
            continue

        filtered.append(arg)

    return filtered


def _runtime_default_model_for_agent(agent_type: str, runtime_config: AgentRuntimeConfig | None) -> str:
    if runtime_config is None:
        return DEFAULT_CLAUDE_MODEL if agent_type == AGENT_TYPE_CLAUDE else ""

    provider_entry = runtime_config.providers.entries.get(agent_type)
    if isinstance(provider_entry, dict):
        provider_model = str(provider_entry.get("model") or "").strip()
        if provider_model:
            return provider_model

    default_model = str(runtime_config.providers.defaults.model or "").strip()
    default_provider = str(runtime_config.providers.defaults.model_provider or "").strip().lower()
    if default_model and (not default_provider or default_provider == str(agent_type or "").strip().lower()):
        return default_model

    if agent_type == AGENT_TYPE_CLAUDE:
        return DEFAULT_CLAUDE_MODEL
    return ""


def _apply_default_model_for_agent(
    agent_type: str,
    agent_args: list[str],
    runtime_config: AgentRuntimeConfig | None = None,
) -> list[str]:
    normalized_args = [str(arg) for arg in agent_args if str(arg).strip()]
    if agent_type != AGENT_TYPE_CLAUDE:
        if agent_type == AGENT_TYPE_CODEX:
            return _strip_explicit_codex_default_model(normalized_args)
        return normalized_args
    if _has_cli_option(normalized_args, long_option="--model", short_option="-m"):
        return normalized_args
    resolved_model = _runtime_default_model_for_agent(agent_type, runtime_config)
    if not resolved_model:
        return normalized_args
    return ["--model", resolved_model, *normalized_args]


def _normalize_chat_layout_engine(raw_value: Any, *, strict: bool = False) -> str:
    value = str(raw_value or "").strip().lower()
    if value in SUPPORTED_CHAT_LAYOUT_ENGINES:
        return value
    if strict:
        supported = ", ".join(sorted(SUPPORTED_CHAT_LAYOUT_ENGINES))
        raise HTTPException(status_code=400, detail=f"chat_layout_engine must be one of: {supported}.")
    return DEFAULT_CHAT_LAYOUT_ENGINE


@lru_cache(maxsize=1)
def _settings_service_defaults() -> SettingsService:
    return SettingsService(
        default_agent_type=DEFAULT_CHAT_AGENT_TYPE,
        default_chat_layout_engine=DEFAULT_CHAT_LAYOUT_ENGINE,
        normalize_chat_agent_type=_normalize_chat_agent_type,
        normalize_chat_layout_engine=_normalize_chat_layout_engine,
    )


def _normalize_chat_status(raw_value: Any, *, strict: bool = False) -> str:
    value = str(raw_value or "").strip().lower()
    if value in SUPPORTED_CHAT_STATUSES:
        return value
    if strict:
        supported = ", ".join(sorted(SUPPORTED_CHAT_STATUSES))
        raise HTTPException(status_code=400, detail=f"chat status must be one of: {supported}.")
    return CHAT_STATUS_STOPPED


def _normalize_optional_int(raw_value: Any) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            return int(raw_value.strip())
        except ValueError:
            return None
    return None


class _StructuredLogDefaultsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return core_logging.StructuredLogDefaultsFilter().filter(record)


def _configure_hub_logging(level: str) -> None:
    normalized = _normalize_log_level(level)
    core_logging.configure_structured_logger(LOGGER, level=normalized)


def _resolve_hub_log_level(log_level: str | None, runtime_config: AgentRuntimeConfig | None) -> str:
    cli_value = str(log_level or "").strip()
    if cli_value:
        return _normalize_log_level(cli_value)

    config_value = ""
    if runtime_config is not None and isinstance(runtime_config.logging.values, dict):
        config_value = str(runtime_config.logging.values.get("level") or "").strip()
    if config_value:
        return _normalize_log_level(config_value)
    return _normalize_log_level("info")


def _configure_domain_log_levels(runtime_config: AgentRuntimeConfig | None) -> None:
    if runtime_config is None or not isinstance(runtime_config.logging.values, dict):
        return
    core_logging.configure_domain_log_levels(
        domains=runtime_config.logging.values.get("domains"),
        logger_prefix="agent_hub",
        normalize_level=_normalize_log_level,
    )


def _core_error_payload(exc: BaseException) -> tuple[int, dict[str, Any]]:
    typed_payload = typed_error_payload(exc)
    if typed_payload is not None:
        status_by_code = {
            "CONFIG_ERROR": 400,
            "IDENTITY_ERROR": 400,
            "MOUNT_VISIBILITY_ERROR": 409,
            "NETWORK_REACHABILITY_ERROR": 502,
            "CREDENTIAL_RESOLUTION_ERROR": 401,
        }
        status = status_by_code.get(str(typed_payload.get("error_code") or ""), 500)
        return status, typed_payload
    return 500, {"error_code": "INTERNAL_ERROR", "detail": str(exc)}


def _http_error_code(status_code: int) -> str:
    status = int(status_code or 500)
    if status == 400:
        return "BAD_REQUEST"
    if status == 401:
        return "UNAUTHORIZED"
    if status == 403:
        return "FORBIDDEN"
    if status == 404:
        return "NOT_FOUND"
    if status == 409:
        return "CONFLICT"
    if status == 422:
        return "UNPROCESSABLE_ENTITY"
    if status == 429:
        return "RATE_LIMITED"
    if status in {500, 502, 503, 504}:
        return "UPSTREAM_ERROR"
    return f"HTTP_{status}"


def _uvicorn_log_level(hub_level: str) -> str:
    normalized = _normalize_log_level(hub_level)
    if normalized == "debug":
        return "info"
    return normalized


def _default_artifact_publish_base_url(hub_port: int) -> str:
    return f"http://{DEFAULT_ARTIFACT_PUBLISH_HOST}:{int(hub_port or DEFAULT_PORT)}"


def _resolve_artifact_publish_base_url(value: Any, hub_port: int) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return _default_artifact_publish_base_url(hub_port)

    parsed = urllib.parse.urlsplit(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(
            "Invalid artifact publish base URL. "
            "Expected an absolute http(s) URL reachable from agent_cli containers."
        )
    normalized_path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def _run_cli_command(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode == 0:
        return
    message = ((result.stdout or "") + (result.stderr or "")).strip()
    if not message:
        message = f"Command failed ({cmd[0]}) with exit code {result.returncode}"
    raise click.ClickException(message)


def _latest_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_mtime
    newest = 0.0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            newest = max(newest, file_path.stat().st_mtime)
    return newest


def _frontend_needs_build(frontend_dir: Path, dist_dir: Path) -> bool:
    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        return True

    dist_mtime = _latest_mtime(dist_dir)
    tracked_sources = [
        frontend_dir / "index.html",
        frontend_dir / "package.json",
        frontend_dir / "yarn.lock",
        frontend_dir / "vite.config.js",
    ]
    for file_path in tracked_sources:
        if file_path.exists() and file_path.stat().st_mtime > dist_mtime:
            return True

    src_dir = frontend_dir / "src"
    if src_dir.exists() and _latest_mtime(src_dir) > dist_mtime:
        return True

    return False


def _ensure_frontend_built(data_dir: Path) -> None:
    frontend_dir = _repo_root() / "web"
    dist_dir = frontend_dir / "dist"

    if not frontend_dir.is_dir():
        raise click.ClickException(f"Missing frontend directory: {frontend_dir}")

    if not _frontend_needs_build(frontend_dir, dist_dir):
        return

    if shutil.which("node") is None:
        raise click.ClickException("node is required to build the frontend, but was not found in PATH.")
    if shutil.which("corepack") is None:
        raise click.ClickException("corepack is required to run Yarn, but was not found in PATH.")

    env = dict(os.environ)
    env.setdefault("COREPACK_HOME", str(data_dir / ".corepack"))

    _run_cli_command(["corepack", "yarn", "install"], cwd=frontend_dir, env=env)
    _run_cli_command(["corepack", "yarn", "build"], cwd=frontend_dir, env=env)


def _frontend_not_built_page() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent Hub Frontend Missing</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #111827; }
    pre { padding: 0.75rem; border: 1px solid #d1d5db; border-radius: 8px; background: #f9fafb; }
  </style>
</head>
<body>
  <h1>Agent Hub frontend is not built</h1>
  <p>Build the React frontend using Yarn, then restart the backend.</p>
  <pre>cd web
yarn install
yarn build</pre>
</body>
</html>
    """


def _github_app_setup_callback_page(success: bool, message: str, app_slug: str = "") -> str:
    status_text = "connected" if success else "failed"
    status_class = "ok" if success else "error"
    title_text = "GitHub Connected" if success else "GitHub Connection Failed"
    escaped_message = html.escape(message or "")
    escaped_slug = html.escape(app_slug or "")
    slug_line = f"<p class=\"meta\">App slug: <code>{escaped_slug}</code></p>" if escaped_slug else ""
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_text}</title>
  <style>
    body {{
      font-family: ui-sans-serif, system-ui, sans-serif;
      margin: 0;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }}
    .panel {{
      width: min(560px, 100%);
      border: 1px solid #1e293b;
      border-radius: 12px;
      background: #111827;
      padding: 1.25rem;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.4);
    }}
    .status {{
      display: inline-block;
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      margin-bottom: 0.75rem;
    }}
    .status.ok {{
      background: rgba(34, 197, 94, 0.2);
      color: #86efac;
    }}
    .status.error {{
      background: rgba(239, 68, 68, 0.2);
      color: #fca5a5;
    }}
    p {{
      margin: 0.5rem 0 0;
      line-height: 1.45;
    }}
    .meta {{
      color: #94a3b8;
      font-size: 0.95rem;
    }}
    .actions {{
      margin-top: 1rem;
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}
    a, button {{
      border: 1px solid #334155;
      border-radius: 8px;
      background: #1e293b;
      color: #e2e8f0;
      padding: 0.5rem 0.9rem;
      text-decoration: none;
      cursor: pointer;
      font: inherit;
    }}
    a:hover, button:hover {{
      border-color: #475569;
    }}
  </style>
</head>
<body>
  <section class="panel">
    <div class="status {status_class}">{status_text}</div>
    <h1>{title_text}</h1>
    <p>{escaped_message}</p>
    {slug_line}
    <div class="actions">
      <a href="/">Return to Agent Hub</a>
      <button type="button" onclick="window.close()">Close window</button>
    </div>
  </section>
</body>
</html>
    """


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return run_command(
        cmd,
        cwd=cwd,
        capture=capture,
        check=check,
        env=env,
    )


def _run_logged(
    cmd: list[str],
    log_path: Path,
    cwd: Path | None = None,
    check: bool = True,
    on_output: Callable[[str], None] | None = None,
    on_process_start: Callable[[subprocess.Popen[str]], None] | None = None,
) -> subprocess.CompletedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command_line = " ".join(cmd)
    start_time = time.monotonic()
    with log_path.open("a", encoding="utf-8", errors="ignore") as log_file:
        start_line = f"$ {command_line}\n"
        log_file.write(start_line)
        log_file.flush()
        if on_output is not None:
            on_output(start_line)
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            start_new_session=True,
        )
        if on_process_start is not None:
            on_process_start(process)
        stdout = process.stdout
        if stdout is not None:
            for line in iter(stdout.readline, ""):
                if line == "":
                    break
                log_file.write(line)
                log_file.flush()
                if on_output is not None:
                    on_output(line)
            stdout.close()
        result = process.wait()
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        completion_line = f"$ exit_code={result} (elapsed_ms={elapsed_ms})\n"
        log_file.write(completion_line)
        log_file.write("\n")
        log_file.flush()
        if on_output is not None:
            on_output(completion_line)
            on_output("\n")
    completed = subprocess.CompletedProcess(cmd, result, "", "")
    if check and completed.returncode != 0:
        command_name = command_line.split(" ", 1)[0] if command_line else "<unknown>"
        LOGGER.warning(
            "Command failed (snapshot task): command=%s exit_code=%s elapsed_ms=%s",
            command_name,
            completed.returncode,
            elapsed_ms,
        )
        raise HTTPException(status_code=400, detail=f"Command failed ({cmd[0]}) with exit code {completed.returncode}")
    LOGGER.debug(
        "Command completed (snapshot task): command=%s exit_code=%s elapsed_ms=%s",
        command_line.split(" ", 1)[0] if command_line else "<unknown>",
        completed.returncode,
        elapsed_ms,
    )
    return completed


def _run_for_repo(
    cmd: list[str],
    repo_dir: Path,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(repo_dir), *cmd], capture=capture, check=check, env=env)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_from_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _new_state() -> dict[str, Any]:
    return {
        "version": 1,
        "projects": {},
        "chats": {},
        "settings": _settings_service_defaults().empty_settings_payload(),
    }


def _normalize_project_credential_binding(raw_binding: Any, *, strict: bool = False) -> dict[str, Any]:
    if not isinstance(raw_binding, dict):
        raw_binding = {}
    raw_mode = str(raw_binding.get("mode") or "").strip().lower()
    mode = raw_mode if raw_mode in PROJECT_CREDENTIAL_BINDING_MODES else PROJECT_CREDENTIAL_BINDING_MODE_AUTO
    if strict and raw_mode and raw_mode not in PROJECT_CREDENTIAL_BINDING_MODES:
        supported = ", ".join(sorted(PROJECT_CREDENTIAL_BINDING_MODES))
        raise CredentialResolutionError(f"credential_binding.mode must be one of: {supported}.")
    raw_ids = raw_binding.get("credential_ids")
    credential_ids: list[str] = []
    if isinstance(raw_ids, list):
        seen: set[str] = set()
        for item in raw_ids:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            credential_ids.append(value)
            seen.add(value)
    source = str(raw_binding.get("source") or "").strip()
    updated_at = str(raw_binding.get("updated_at") or "").strip()
    return {
        "mode": mode,
        "credential_ids": credential_ids,
        "source": source,
        "updated_at": updated_at,
    }


def _ordered_supported_agent_types() -> tuple[str, ...]:
    return (
        AGENT_TYPE_CODEX,
        AGENT_TYPE_CLAUDE,
        AGENT_TYPE_GEMINI,
    )


def _normalize_mode_options(raw_values: Any, fallback: list[str]) -> list[str]:
    values = list(fallback)
    if isinstance(raw_values, list):
        values = [str(item or "").strip() for item in raw_values]
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    if "default" in seen:
        normalized = ["default", *[item for item in normalized if item != "default"]]
    else:
        normalized = ["default", *normalized]
    if not normalized:
        return ["default"]
    return normalized


def _normalize_model_options_for_agent(agent_type: str, raw_values: Any, fallback: list[str]) -> list[str]:
    del fallback
    candidate_values = _normalize_mode_options(raw_values, ["default"])
    filtered = ["default"]
    seen = {"default"}
    for value in candidate_values:
        if value in seen:
            continue
        if value == "default":
            continue
        if not _token_is_model_candidate(agent_type, value):
            continue
        filtered.append(value)
        seen.add(value)
    return filtered


def _normalize_reasoning_mode_options_for_agent(agent_type: str, raw_values: Any, fallback: list[str]) -> list[str]:
    del fallback
    candidate_values = _normalize_mode_options(raw_values, ["default"])
    candidate_levels = [value for value in candidate_values if _token_is_reasoning_candidate(agent_type, value)]
    if candidate_levels:
        return ["default", *candidate_levels]
    return ["default"]


def _agent_capability_defaults_for_type(agent_type: str) -> dict[str, Any]:
    resolved_type = _normalize_chat_agent_type(agent_type, strict=True)
    default_models = AGENT_CAPABILITY_DEFAULT_MODELS_BY_TYPE.get(
        resolved_type,
        AGENT_CAPABILITY_DEFAULT_MODELS_BY_TYPE[DEFAULT_CHAT_AGENT_TYPE],
    )
    default_reasoning = AGENT_CAPABILITY_DEFAULT_REASONING_BY_TYPE.get(
        resolved_type,
        AGENT_CAPABILITY_DEFAULT_REASONING_BY_TYPE[DEFAULT_CHAT_AGENT_TYPE],
    )
    return {
        "agent_type": resolved_type,
        "label": AGENT_LABEL_BY_TYPE.get(resolved_type, resolved_type.title()),
        "models": _normalize_model_options_for_agent(resolved_type, default_models, ["default"]),
        "reasoning_modes": _normalize_reasoning_mode_options_for_agent(resolved_type, default_reasoning, ["default"]),
        "updated_at": "",
        "last_error": "",
    }


def _default_agent_capabilities_cache_payload() -> dict[str, Any]:
    agents = [_agent_capability_defaults_for_type(agent_type) for agent_type in _ordered_supported_agent_types()]
    return {
        "version": 1,
        "updated_at": "",
        "discovery_in_progress": False,
        "discovery_started_at": "",
        "discovery_finished_at": "",
        "agents": agents,
    }


def _normalize_agent_capabilities_payload(raw_payload: Any) -> dict[str, Any]:
    defaults = _default_agent_capabilities_cache_payload()
    if not isinstance(raw_payload, dict):
        return defaults

    raw_agents = raw_payload.get("agents")
    raw_agent_map: dict[str, dict[str, Any]] = {}
    if isinstance(raw_agents, list):
        for raw_agent in raw_agents:
            if not isinstance(raw_agent, dict):
                continue
            resolved_type = _normalize_chat_agent_type(raw_agent.get("agent_type"), strict=True)
            raw_agent_map[resolved_type] = raw_agent

    normalized_agents: list[dict[str, Any]] = []
    for agent_type in _ordered_supported_agent_types():
        defaults_for_type = _agent_capability_defaults_for_type(agent_type)
        raw_agent = raw_agent_map.get(agent_type, {})
        label = str(raw_agent.get("label") or defaults_for_type["label"]).strip() or defaults_for_type["label"]
        models = _normalize_model_options_for_agent(agent_type, raw_agent.get("models"), defaults_for_type["models"])
        reasoning_modes = _normalize_reasoning_mode_options_for_agent(
            agent_type,
            raw_agent.get("reasoning_modes"),
            defaults_for_type["reasoning_modes"],
        )
        updated_at = str(raw_agent.get("updated_at") or raw_payload.get("updated_at") or "").strip()
        last_error = str(raw_agent.get("last_error") or "").strip()
        normalized_agents.append(
            {
                "agent_type": agent_type,
                "label": label,
                "models": models,
                "reasoning_modes": reasoning_modes,
                "updated_at": updated_at,
                "last_error": last_error,
            }
        )

    return {
        "version": 1,
        "updated_at": str(raw_payload.get("updated_at") or "").strip(),
        "discovery_in_progress": bool(raw_payload.get("discovery_in_progress")),
        "discovery_started_at": str(raw_payload.get("discovery_started_at") or "").strip(),
        "discovery_finished_at": str(raw_payload.get("discovery_finished_at") or "").strip(),
        "agents": normalized_agents,
    }


def _token_is_model_candidate(agent_type: str, token: str) -> bool:
    value = str(token or "").strip().lower()
    if not value or value == "default":
        return False
    if agent_type == AGENT_TYPE_CODEX:
        if value in {"codex", "codex-provided"}:
            return False
        return AGENT_CAPABILITY_CODEX_MODEL_TOKEN_RE.match(value) is not None
    if agent_type == AGENT_TYPE_CLAUDE:
        if value in {"claude", "claude-code"}:
            return False
        return (
            value.startswith("claude-")
            or value.startswith("sonnet")
            or value.startswith("opus")
            or value.startswith("haiku")
            or value in {"sonnet", "opus", "haiku"}
        )
    if agent_type == AGENT_TYPE_GEMINI:
        return value.startswith("gemini") or value in AGENT_CAPABILITY_GEMINI_MODEL_ALIASES
    return False


def _option_count_excluding_default(values: list[str]) -> int:
    return sum(1 for value in values if str(value or "").strip().lower() != "default")


def _token_is_reasoning_candidate(agent_type: str, token: str) -> bool:
    value = str(token or "").strip().lower()
    if not value or value == "default":
        return False
    levels = AGENT_CAPABILITY_REASONING_LEVELS_BY_TYPE.get(agent_type, ())
    return value in levels


def _fetch_codex_models_from_docs(timeout_seconds: float) -> list[str]:
    request = urllib.request.Request(
        AGENT_CAPABILITY_CODEX_MODELS_DOC_URL,
        headers={
            "Accept": "text/html",
            "User-Agent": "agent-hub-capability-discovery/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout_seconds))) as response:
            status = int(response.getcode() or 0)
            body = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"failed to fetch {AGENT_CAPABILITY_CODEX_MODELS_DOC_URL}: {exc}") from exc

    if status != 200:
        raise RuntimeError(
            f"failed to fetch {AGENT_CAPABILITY_CODEX_MODELS_DOC_URL}: HTTP {status}"
        )

    text = html.unescape(str(body or ""))
    discovered: list[str] = []
    seen: set[str] = set()

    # Prefer model card names from docs so we capture entries that do not have a
    # unique `codex -m ...` command token in the rendered examples.
    for match in AGENT_CAPABILITY_CODEX_MODELS_DOC_NAME_RE.finditer(text):
        token = str(match.group(1) or "").strip().lower()
        if not token or token in seen:
            continue
        if not _token_is_model_candidate(AGENT_TYPE_CODEX, token):
            continue
        seen.add(token)
        discovered.append(token)

    if discovered:
        return discovered

    for match in AGENT_CAPABILITY_CODEX_MODELS_DOC_MODEL_RE.finditer(text):
        token = str(match.group(1) or "").strip().lower()
        if not token or token in seen:
            continue
        if not _token_is_model_candidate(AGENT_TYPE_CODEX, token):
            continue
        seen.add(token)
        discovered.append(token)
    return discovered


def _extract_models_from_json_payload(payload: Any, agent_type: str) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    model_keys = {"model", "name", "id", "slug", "display_name"}

    def add(value: Any) -> None:
        token = str(value or "").strip().lower()
        if not _token_is_model_candidate(agent_type, token) or token in seen:
            return
        seen.add(token)
        discovered.append(token)

    def walk(node: Any, parent_key: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                normalized_key = str(key or "").strip().lower().replace("-", "_")
                if normalized_key in model_keys:
                    add(value)
                if isinstance(value, (dict, list)):
                    walk(value, normalized_key)
            return
        if isinstance(node, list):
            for item in node:
                walk(item, parent_key or "models")
            return
        if isinstance(node, str):
            if parent_key in model_keys or parent_key == "models":
                add(node)

    walk(payload)
    return discovered


def _extract_model_candidates_from_output(output_text: str, agent_type: str) -> list[str]:
    text = str(output_text or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
        if isinstance(payload, (dict, list)):
            parsed = _extract_models_from_json_payload(payload, agent_type)
            if parsed:
                return parsed
    except json.JSONDecodeError:
        pass

    help_candidates = _extract_option_values_from_help_text(
        text,
        option_name_matcher=lambda option_name: option_name == "model" or option_name.endswith("-model"),
        token_validator=lambda token: _token_is_model_candidate(agent_type, token),
        contextual_list_pattern=AGENT_CAPABILITY_MODEL_LIST_RE,
    )
    if help_candidates:
        return help_candidates

    # Some CLIs print numbered model menus without explicit --model context.
    # Capture leading list tokens so capability discovery still reflects available models.
    discovered: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = str(raw_line or "").rstrip()
        if not line:
            continue
        numbered_match = AGENT_CAPABILITY_HELP_NUMBERED_VALUE_RE.match(line)
        if not numbered_match:
            continue
        token = str(numbered_match.group(1) or "").strip().lower().strip(".,;:()[]{}")
        if not token or token in seen:
            continue
        if not _token_is_model_candidate(agent_type, token):
            continue
        seen.add(token)
        discovered.append(token)
    return discovered


def _extract_option_values_from_help_text(
    help_text: str,
    *,
    option_name_matcher: Callable[[str], bool],
    token_validator: Callable[[str], bool],
    contextual_list_pattern: re.Pattern[str] | None = None,
) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    active_option_matches = False
    collect_bullet_values = False

    def add_token(raw_token: str) -> None:
        token = str(raw_token or "").strip().lower().strip(".,;:()[]{}")
        if not token or token in seen:
            return
        if not token_validator(token):
            return
        seen.add(token)
        discovered.append(token)

    def add_segment(raw_segment: str) -> None:
        for raw_token in AGENT_CAPABILITY_HELP_TOKEN_RE.findall(str(raw_segment or "")):
            add_token(raw_token)

    lines = str(help_text or "").splitlines()
    for raw_line in lines:
        line = str(raw_line or "").rstrip()
        lower_line = line.lower()
        option_names = [name.lower() for name in AGENT_CAPABILITY_HELP_OPTION_RE.findall(lower_line)]
        if option_names:
            active_option_matches = any(option_name_matcher(name) for name in option_names)
            collect_bullet_values = False

        if active_option_matches:
            # Parse the active option line directly so "e.g. 'sonnet' or 'opus'" style guidance is discovered.
            add_segment(line)
            for match in AGENT_CAPABILITY_HELP_INLINE_VALUES_RE.finditer(line):
                add_segment(match.group(1))

            has_inline_list_values = False
            for match in AGENT_CAPABILITY_HELP_LIST_VALUE_RE.finditer(line):
                add_segment(match.group(1))
                has_inline_list_values = True

            if AGENT_CAPABILITY_HELP_LIST_MARKER_RE.search(lower_line) and not has_inline_list_values:
                collect_bullet_values = True
                continue

        if collect_bullet_values:
            bullet_match = AGENT_CAPABILITY_HELP_BULLET_VALUE_RE.match(line)
            if bullet_match:
                add_token(bullet_match.group(1))
                continue
            numbered_match = AGENT_CAPABILITY_HELP_NUMBERED_VALUE_RE.match(line)
            if numbered_match:
                add_token(numbered_match.group(1))
                continue
            if not line.strip():
                collect_bullet_values = False

    if contextual_list_pattern is not None:
        for match in contextual_list_pattern.finditer(help_text):
            add_segment(match.group(1))

    return discovered


def _extract_reasoning_candidates_from_output(output_text: str, agent_type: str) -> list[str]:
    text = str(output_text or "")
    if not text:
        return []
    lower_text = text.lower()
    discovered: list[str] = []
    seen: set[str] = set()

    def add_token(raw_token: str) -> None:
        token = str(raw_token or "").strip().lower().strip(".,;:()[]{}")
        if not token or token in seen:
            return
        if not _token_is_reasoning_candidate(agent_type, token):
            return
        seen.add(token)
        discovered.append(token)

    def add_from_text(value: str) -> None:
        for token in AGENT_CAPABILITY_REASONING_VALUE_RE.findall(str(value or "").lower()):
            add_token(token)
        for token in AGENT_CAPABILITY_HELP_TOKEN_RE.findall(str(value or "").lower()):
            add_token(token)

    def maybe_normalized(values: list[str]) -> list[str]:
        normalized = _normalize_mode_options(values, ["default"])
        if _option_count_excluding_default(normalized) < 2:
            return []
        return normalized

    help_candidates = _extract_option_values_from_help_text(
        text,
        option_name_matcher=lambda option_name: any(
            keyword in option_name for keyword in ("effort", "reasoning", "thinking")
        ),
        token_validator=lambda token: _token_is_reasoning_candidate(agent_type, token),
        contextual_list_pattern=AGENT_CAPABILITY_REASONING_LIST_RE,
    )
    if help_candidates:
        normalized_help = maybe_normalized(help_candidates)
        if normalized_help:
            return normalized_help

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, (dict, list)):
        keys_with_mode_lists = {
            "reasoning_modes",
            "supported_reasoning_modes",
            "supported_reasoning",
            "reasoning_mode_options",
            "supported_reasoning_levels",
            "effort_levels",
            "supported_effort_levels",
            "supported_effort",
            "supported_thinking_levels",
            "thinking_levels",
        }

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    normalized_key = str(key or "").strip().lower().replace("-", "_")
                    if normalized_key in keys_with_mode_lists:
                        if isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict):
                                    add_from_text(
                                        str(
                                            item.get("effort")
                                            or item.get("level")
                                            or item.get("name")
                                            or item.get("value")
                                            or ""
                                        )
                                    )
                                else:
                                    add_from_text(str(item or ""))
                        elif isinstance(value, dict):
                            add_from_text(
                                str(
                                    value.get("effort")
                                    or value.get("level")
                                    or value.get("name")
                                    or value.get("value")
                                    or ""
                                )
                            )
                        elif isinstance(value, str):
                            add_from_text(value)
                    if isinstance(value, (dict, list)):
                        walk(value)
                return
            if isinstance(node, list):
                for item in node:
                    if isinstance(item, (dict, list)):
                        walk(item)

        walk(payload)
        normalized_json = maybe_normalized(discovered)
        if normalized_json:
            return normalized_json

    has_reasoning_context = any(
        marker in lower_text
        for marker in (
            "model_reasoning_effort",
            "reasoning_effort",
            "reasoning effort",
            "thinking_level",
            "thinking level",
        )
    )
    if has_reasoning_context:
        for match in AGENT_CAPABILITY_REASONING_EXPECTED_VALUES_RE.finditer(text):
            add_from_text(match.group(1))
        normalized_expected_values = maybe_normalized(discovered)
        if normalized_expected_values:
            return normalized_expected_values

    for match in AGENT_CAPABILITY_REASONING_LIST_RE.finditer(text):
        add_from_text(match.group(1))
    normalized_text = maybe_normalized(discovered)
    if normalized_text:
        return normalized_text
    return []


def _agent_capability_probe_docker_run_args(
    *,
    local_uid: int,
    local_gid: int,
    local_supp_gids_csv: str,
    local_umask: str,
    local_user: str,
    host_codex_dir: Path,
    config_file: Path,
) -> list[str]:
    container_home = DEFAULT_CONTAINER_HOME
    run_args = [
        "--init",
        "--user",
        f"{local_uid}:{local_gid}",
        "--workdir",
        container_home,
        "--tmpfs",
        TMP_DIR_TMPFS_SPEC,
        "--volume",
        f"{host_codex_dir}:{container_home}/.codex",
        "--volume",
        f"{config_file}:{container_home}/.codex/config.toml",
        "--env",
        f"LOCAL_UMASK={local_umask}",
        "--env",
        f"LOCAL_USER={local_user}",
        "--env",
        f"HOME={container_home}",
        "--env",
        "NPM_CONFIG_CACHE=/tmp/.npm",
        "--env",
        f"CONTAINER_HOME={container_home}",
        "--env",
        f"PATH={container_home}/.codex/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    ]
    run_args.extend(["--group-add", "agent"])
    for supp_gid in _parse_gid_csv(local_supp_gids_csv):
        if supp_gid == local_gid:
            continue
        run_args.extend(["--group-add", str(supp_gid)])
    return run_args


def _run_agent_capability_probe(
    cmd: list[str],
    timeout_seconds: float,
    *,
    docker_run_args: list[str] | None = None,
) -> tuple[int, str]:
    tokens = [str(token).strip() for token in cmd if str(token).strip()]
    if not tokens:
        return 2, "empty capability probe command"

    provider = _agent_capability_provider_for_command(tokens[0])
    if not provider:
        return 2, f"unsupported capability probe command: {tokens[0]}"

    try:
        runtime_image = _ensure_agent_capability_runtime_image(provider)
    except RuntimeError as exc:
        return 125, str(exc)

    docker_cmd = ["docker", "run", "--rm", *(docker_run_args or []), runtime_image, *tokens]
    try:
        result = subprocess.run(
            docker_cmd,
            check=False,
            text=True,
            capture_output=True,
            timeout=max(1.0, float(timeout_seconds)),
        )
        output_text = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
        return result.returncode, output_text
    except subprocess.TimeoutExpired as exc:
        output_text = f"{exc.stdout or ''}\n{exc.stderr or ''}".strip()
        return 124, output_text
    except FileNotFoundError:
        return 125, "docker command not found in PATH"


def _agent_capability_provider_for_command(command: str) -> str:
    normalized_command = Path(str(command or "").strip()).name.lower()
    for agent_type, agent_command in AGENT_COMMAND_BY_TYPE.items():
        if normalized_command == str(agent_command).strip().lower():
            return agent_type
    return ""


def _ensure_agent_capability_runtime_image(agent_provider: str) -> str:
    normalized_provider = _normalize_chat_agent_type(agent_provider, strict=True)
    base_image = agent_cli_image.DEFAULT_BASE_IMAGE
    runtime_image = agent_cli_image._default_runtime_image_for_provider(normalized_provider)
    try:
        agent_cli_image._ensure_runtime_image_built_if_missing(
            base_image=base_image,
            target_image=runtime_image,
            agent_provider=normalized_provider,
        )
    except click.ClickException as exc:
        raise RuntimeError(
            "Capability discovery runtime image build failed "
            f"(base_image={base_image}, provider={normalized_provider}, target_image={runtime_image}): {exc}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError("docker command not found in PATH") from exc
    return runtime_image


def _read_openai_api_key(path: Path) -> str | None:
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    for line in text.splitlines():
        match = re.match(r"^\s*OPENAI_API_KEY\s*=\s*(.+?)\s*$", line)
        if not match:
            continue
        value = match.group(1).strip().strip('"').strip("'")
        if value:
            return value
    return None


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _normalize_openai_api_key(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="api_key is required.")
    if any(ch.isspace() for ch in value):
        raise HTTPException(status_code=400, detail="OpenAI API key must not contain whitespace.")
    if len(value) < 20:
        raise HTTPException(status_code=400, detail="OpenAI API key appears too short.")
    return value


def _normalize_github_app_id(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError(f"{GITHUB_APP_ID_ENV} is required.")
    if not value.isdigit():
        raise ValueError(f"{GITHUB_APP_ID_ENV} must be numeric.")
    return value


def _normalize_github_app_slug(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    if not value:
        raise ValueError(f"{GITHUB_APP_SLUG_ENV} is required.")
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise ValueError(f"{GITHUB_APP_SLUG_ENV} must contain only lowercase letters, numbers, and hyphens.")
    return value


def _normalize_github_app_private_key(raw_value: Any) -> str:
    value = str(raw_value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        raise ValueError("GitHub App private key is required.")
    if "\x00" in value:
        raise ValueError("GitHub App private key contains invalid binary data.")
    if len(value) > GITHUB_APP_PRIVATE_KEY_MAX_CHARS:
        raise ValueError("GitHub App private key is too large.")

    lines = [line.rstrip() for line in value.split("\n")]
    if not lines:
        raise ValueError("GitHub App private key is required.")
    begin_marker = lines[0].strip()
    end_marker = lines[-1].strip()
    if begin_marker not in GITHUB_APP_PRIVATE_KEY_BEGIN_MARKERS or end_marker not in GITHUB_APP_PRIVATE_KEY_END_MARKERS:
        raise ValueError("GitHub App private key must be a PEM key (BEGIN/END PRIVATE KEY).")
    if begin_marker.replace("BEGIN", "END") != end_marker:
        raise ValueError("GitHub App private key BEGIN/END markers do not match.")
    if len(lines) < 3:
        raise ValueError("GitHub App private key appears incomplete.")

    return "\n".join(lines) + "\n"


def _normalize_absolute_http_base_url(raw_value: Any, field_name: str) -> str:
    value = str(raw_value or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute http(s) URL.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _github_app_env_config_present() -> bool:
    return any(
        str(os.environ.get(name, "")).strip()
        for name in (
            GITHUB_APP_ID_ENV,
            GITHUB_APP_SLUG_ENV,
            GITHUB_APP_PRIVATE_KEY_ENV,
            GITHUB_APP_PRIVATE_KEY_FILE_ENV,
        )
    )


def _normalize_github_app_settings_payload(payload: dict[str, Any], source_name: str) -> GithubAppSettings:
    if not isinstance(payload, dict):
        raise ValueError(f"{source_name} must be a JSON object.")

    app_id_raw = payload.get("app_id")
    if app_id_raw is None:
        app_id_raw = payload.get("id")

    slug_raw = payload.get("app_slug")
    if slug_raw is None:
        slug_raw = payload.get("slug")

    key_raw = payload.get("private_key")
    if key_raw is None:
        key_raw = payload.get("pem")

    web_base_raw = payload.get("web_base_url")
    if web_base_raw is None or not str(web_base_raw).strip():
        web_base_raw = GITHUB_APP_DEFAULT_WEB_BASE_URL

    api_base_raw = payload.get("api_base_url")
    if api_base_raw is None or not str(api_base_raw).strip():
        api_base_raw = GITHUB_APP_DEFAULT_API_BASE_URL

    try:
        app_id = _normalize_github_app_id(app_id_raw)
        app_slug = _normalize_github_app_slug(slug_raw)
        private_key = _normalize_github_app_private_key(key_raw)
        web_base = _normalize_absolute_http_base_url(web_base_raw, "web_base_url")
        api_base = _normalize_absolute_http_base_url(api_base_raw, "api_base_url")
    except ValueError as exc:
        raise ValueError(f"{source_name}: {exc}") from exc

    return GithubAppSettings(
        app_id=app_id,
        app_slug=app_slug,
        private_key=private_key,
        web_base_url=web_base,
        api_base_url=api_base,
    )


def _load_github_app_settings_from_env() -> tuple[GithubAppSettings | None, str]:
    app_id_raw = str(os.environ.get(GITHUB_APP_ID_ENV, "")).strip()
    slug_raw = str(os.environ.get(GITHUB_APP_SLUG_ENV, "")).strip()
    key_raw = str(os.environ.get(GITHUB_APP_PRIVATE_KEY_ENV, "")).strip()
    key_file_raw = str(os.environ.get(GITHUB_APP_PRIVATE_KEY_FILE_ENV, "")).strip()

    if not app_id_raw and not slug_raw and not key_raw and not key_file_raw:
        return None, ""
    if bool(key_raw) and bool(key_file_raw):
        return None, (
            f"Set only one of {GITHUB_APP_PRIVATE_KEY_ENV} or {GITHUB_APP_PRIVATE_KEY_FILE_ENV}, not both."
        )

    if key_file_raw and not key_raw:
        key_path = Path(key_file_raw).expanduser()
        if not key_path.is_file():
            return None, f"{GITHUB_APP_PRIVATE_KEY_FILE_ENV} does not point to a readable file."
        try:
            key_raw = key_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None, f"Failed to read {GITHUB_APP_PRIVATE_KEY_FILE_ENV}."

    try:
        settings = _normalize_github_app_settings_payload(
            {
                "app_id": app_id_raw,
                "app_slug": slug_raw,
                "private_key": key_raw,
                "web_base_url": str(
                    os.environ.get(GITHUB_APP_WEB_BASE_URL_ENV, GITHUB_APP_DEFAULT_WEB_BASE_URL)
                ).strip(),
                "api_base_url": str(
                    os.environ.get(GITHUB_APP_API_BASE_URL_ENV, GITHUB_APP_DEFAULT_API_BASE_URL)
                ).strip(),
            },
            "GitHub App environment variables",
        )
    except ValueError as exc:
        return None, str(exc)
    return settings, ""


def _load_github_app_settings_from_file(path: Path) -> tuple[GithubAppSettings | None, str]:
    if not path.exists():
        return None, ""
    payload = _read_json_if_exists(path)
    if payload is None:
        return None, f"Stored GitHub App settings file is invalid: {path}"
    try:
        settings = _normalize_github_app_settings_payload(payload, "Stored GitHub App settings")
    except ValueError as exc:
        return None, str(exc)
    return settings, ""


def _normalize_github_installation_id(raw_value: Any) -> int:
    value = str(raw_value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="installation_id is required.")
    if not value.isdigit():
        raise HTTPException(status_code=400, detail="installation_id must be a positive integer.")
    installation_id = int(value)
    if installation_id <= 0:
        raise HTTPException(status_code=400, detail="installation_id must be a positive integer.")
    return installation_id


def _split_host_port(host: str) -> tuple[str, int | None]:
    try:
        return core_shared.split_host_port(
            host,
            error_factory=lambda _message: HTTPException(status_code=400, detail=f"Invalid host: {host}"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid host: {host}") from exc


def _normalize_github_credential_scheme(raw_value: Any, field_name: str = "scheme") -> str:
    scheme = str(raw_value or "").strip().lower() or GIT_CREDENTIAL_DEFAULT_SCHEME
    if scheme not in GIT_CREDENTIAL_ALLOWED_SCHEMES:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}")
    return scheme


def _normalize_github_credential_endpoint(
    raw_value: Any,
    field_name: str = "host",
    default_scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME,
) -> tuple[str, str]:
    candidate = str(raw_value or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail=f"{field_name} is required.")

    default_scheme_value = _normalize_github_credential_scheme(default_scheme, field_name=f"{field_name}_scheme")
    scheme = default_scheme_value
    host_value = candidate

    if "://" in candidate:
        parsed = urllib.parse.urlsplit(candidate)
        scheme = _normalize_github_credential_scheme(parsed.scheme, field_name=f"{field_name}_scheme")
        if parsed.username or parsed.password:
            raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}")
        hostname = str(parsed.hostname or "").strip().lower()
        if not hostname:
            raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}")
        try:
            port = parsed.port
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}") from exc
        host_value = f"{hostname}:{port}" if port else hostname
    else:
        host_value = candidate.lower()

    hostname, port = _split_host_port(host_value)
    if not hostname:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}")
    if not re.fullmatch(r"[a-z0-9.-]+", hostname):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {raw_value}")
    normalized_host = f"{hostname}:{port}" if port else hostname
    return scheme, normalized_host


def _normalize_github_credential_host(raw_value: Any, field_name: str = "host") -> str:
    _scheme, host = _normalize_github_credential_endpoint(raw_value, field_name=field_name)
    return host


def _normalize_github_personal_access_token(raw_value: Any) -> str:
    token = str(raw_value or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="personal_access_token is required.")
    if any(ch.isspace() for ch in token):
        raise HTTPException(status_code=400, detail="personal_access_token must not contain whitespace.")
    if len(token) < GITHUB_PERSONAL_ACCESS_TOKEN_MIN_CHARS:
        raise HTTPException(status_code=400, detail="personal_access_token appears too short.")
    return token


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _github_sign_rs256(
    private_key_pem: str,
    message: bytes,
    temp_root_dir: Path,
) -> bytes:
    temp_root = Path(temp_root_dir).resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_key_path = temp_root / f".agent_hub_github_app_key_{uuid.uuid4().hex}.pem"
    _write_private_env_file(temp_key_path, private_key_pem)
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(temp_key_path)],
            input=message,
            capture_output=True,
            check=False,
        )
    finally:
        try:
            temp_key_path.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail="Failed to sign GitHub App JWT with OpenSSL.")
    return result.stdout


def _github_app_jwt(settings: GithubAppSettings, temp_root_dir: Path) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 30,
        "exp": now + GITHUB_APP_JWT_LIFETIME_SECONDS,
        "iss": settings.app_id,
    }
    header_segment = _base64url_encode(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload_segment = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature_segment = _base64url_encode(_github_sign_rs256(settings.private_key, signing_input, temp_root_dir))
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _iso_to_unix_seconds(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


def _github_api_error_message(body_text: str) -> str:
    text = str(body_text or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _short_summary(text, max_words=24, max_chars=200)
    if not isinstance(payload, dict):
        return ""
    message = str(payload.get("message") or "").strip()
    return _short_summary(message, max_words=24, max_chars=200) if message else ""


def _git_repo_host(repo_url: str) -> str:
    candidate = str(repo_url or "").strip()
    if not candidate:
        return ""

    parsed = urllib.parse.urlsplit(candidate)
    if parsed.hostname:
        host = parsed.hostname.lower()
        try:
            port = parsed.port
        except ValueError:
            port = None
        return f"{host}:{port}" if port else host

    scp_match = re.match(r"^[^@]+@([^:]+):", candidate)
    if scp_match:
        return scp_match.group(1).lower().strip()

    ssh_match = re.match(r"^ssh://[^@]+@([^/]+)/", candidate)
    if ssh_match:
        return ssh_match.group(1).lower().strip()

    return ""


def _git_repo_scheme(repo_url: str) -> str:
    candidate = str(repo_url or "").strip()
    if not candidate:
        return ""

    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme:
        return parsed.scheme.lower().strip()

    if re.match(r"^[^@]+@[^:]+:", candidate):
        return "ssh"
    return ""


def _project_repo_url_validation_error(repo_url: str) -> str:
    candidate = str(repo_url or "").strip()
    if not candidate:
        return "repo_url is required."

    scheme = _git_repo_scheme(candidate)
    is_scp_ssh = bool(re.match(r"^[^@\s]+@[^:\s]+:.+$", candidate))
    if scheme in {"ssh", "git+ssh"} or is_scp_ssh:
        return (
            "SSH repository URLs are not supported yet. "
            "Use an HTTPS repository URL (for example, https://github.com/org/repo.git)."
        )
    if scheme not in {"http", "https"}:
        return (
            "Only HTTP(S) repository URLs are supported right now. "
            "Use an HTTPS repository URL (for example, https://github.com/org/repo.git)."
        )
    return ""


def _git_repo_owner(repo_url: str) -> str:
    candidate = str(repo_url or "").strip()
    if not candidate:
        return ""

    parsed = urllib.parse.urlsplit(candidate)
    repo_path = ""
    if parsed.hostname:
        repo_path = str(parsed.path or "").strip()
    else:
        scp_match = re.match(r"^[^@]+@[^:]+:(.+)$", candidate)
        if scp_match:
            repo_path = str(scp_match.group(1) or "").strip()
        else:
            ssh_match = re.match(r"^ssh://[^@]+@[^/]+/(.+)$", candidate)
            if ssh_match:
                repo_path = str(ssh_match.group(1) or "").strip()
    if not repo_path:
        return ""

    parts = [part for part in repo_path.split("/") if part]
    if len(parts) < 2:
        return ""
    owner = str(parts[0] or "").strip().lower()
    if not owner:
        return ""
    return owner


def _openai_error_message(body_text: str) -> str:
    text = str(body_text or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _short_summary(text, max_words=20, max_chars=180)

    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    message = str(error.get("message") or "").strip()
    return _short_summary(message, max_words=30, max_chars=220) if message else ""


def _coerce_bool(value: Any, default: bool, field_name: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    raise HTTPException(status_code=400, detail=f"{field_name} must be a boolean.")


def _normalize_openai_account_login_method(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    if not value:
        return "browser_callback"
    if value in {"browser_callback", "device_auth"}:
        return value
    raise HTTPException(status_code=400, detail="method must be 'browser_callback' or 'device_auth'.")


def _verify_openai_api_key(api_key: str, timeout_seconds: float = 8.0) -> None:
    request = urllib.request.Request(
        "https://api.openai.com/v1/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.getcode() or 0)
            body = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        status = int(exc.code or 0)
        body = exc.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to verify OpenAI API key due to a network error.",
        ) from exc

    if status == 200:
        return

    message = _openai_error_message(body)
    if status in {401, 403}:
        detail = "OpenAI rejected the API key."
        if message:
            detail = f"{detail} {message}"
        raise HTTPException(status_code=400, detail=detail)

    detail = f"OpenAI verification failed with status {status}."
    if message:
        detail = f"{detail} {message}"
    raise HTTPException(status_code=502, detail=detail)


def _write_private_env_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _agent_tools_mcp_source_path() -> Path:
    return Path(__file__).resolve().with_name(AGENT_TOOLS_MCP_RUNTIME_FILE_NAME)


def _empty_list(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise HTTPException(status_code=400, detail="Expected an array.")
    parsed: list[str] = []
    for raw in v:
        if not isinstance(raw, str):
            raise HTTPException(status_code=400, detail="Entries must be strings.")
        parsed.append(raw.strip())
    return [item for item in parsed if item]


def _parse_mounts(entries: list[str], direction: str) -> list[str]:
    output: list[str] = []
    for entry in entries:
        if ":" not in entry:
            raise HTTPException(status_code=400, detail=f"Invalid {direction} mount '{entry}'.")
        host, container = entry.split(":", 1)
        host_path = Path(host).expanduser()
        if not host_path.exists():
            raise HTTPException(status_code=400, detail=f"Host path for {direction} mount does not exist: {host}")
        output.append(f"{host_path}:{container}")
    return output


def _mount_container_target(entry: str) -> str:
    if ":" not in entry:
        return ""
    _host, container = entry.split(":", 1)
    # Keep only the container path portion before optional mode suffix.
    path = str(container or "").split(":", 1)[0].strip()
    if not path:
        return ""
    return str(PurePosixPath(path))


def _contains_container_mount_target(entries: list[str], container_path: str) -> bool:
    expected = str(PurePosixPath(str(container_path or "").strip() or "/"))
    if not expected:
        return False
    for entry in entries:
        if _mount_container_target(str(entry or "")) == expected:
            return True
    return False


def _parse_env_vars(entries: list[str]) -> list[str]:
    output: list[str] = []
    for entry in entries:
        if "=" not in entry:
            raise HTTPException(status_code=400, detail=f"Invalid environment variable '{entry}'. Expected KEY=VALUE.")
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise HTTPException(status_code=400, detail=f"Invalid environment variable '{entry}'. Empty key.")
        if any(ch.isspace() for ch in key):
            raise HTTPException(status_code=400, detail=f"Invalid environment variable key '{key}'.")
        if key.upper() in RESERVED_ENV_VAR_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"{key} is managed in Settings > Authentication and cannot be set manually.",
            )
        output.append(f"{key}={value}")
    return output


def _is_reserved_env_entry(entry: str) -> bool:
    if "=" not in entry:
        return False
    key = entry.split("=", 1)[0].strip().upper()
    return key in RESERVED_ENV_VAR_KEYS


def _docker_image_exists(tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", tag],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _normalize_base_image_mode(mode: Any) -> str:
    if mode is None:
        return "tag"
    normalized = str(mode).strip().lower()
    if normalized in {"tag", "repo_path"}:
        return normalized
    raise HTTPException(status_code=400, detail="base_image_mode must be 'tag' or 'repo_path'.")


def _normalize_base_image_value(mode: Any, value: Any) -> str:
    normalized_mode = _normalize_base_image_mode(mode)
    normalized_value = str(value or "").strip()
    if normalized_mode == "tag":
        return normalized_value or str(agent_cli_image.DEFAULT_BASE_IMAGE)
    return normalized_value


def _extract_repo_name(repo_url: str) -> str:
    name = repo_url.rstrip("/").split(":")[-1].rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _sanitize_workspace_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "project"


def _container_project_name(value: Any) -> str:
    return _sanitize_workspace_component(str(value or ""))


def _container_workspace_path_for_project(value: Any) -> str:
    return str(PurePosixPath(DEFAULT_CONTAINER_HOME) / _container_project_name(value))


def _upsert_codex_trusted_project_config(base_config_text: str, container_project_path: str) -> str:
    normalized_path = str(container_project_path or "").strip()
    if not normalized_path:
        return str(base_config_text or "")
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path.lstrip("/")
    assignment_key = f"projects.{json.dumps(normalized_path)}.trust_level"
    pattern = re.compile(rf"(?m)^\s*{re.escape(assignment_key)}\s*=.*\n?")
    cleaned = re.sub(pattern, "", str(base_config_text or ""))
    return f"{cleaned.rstrip()}\n{assignment_key} = \"trusted\"\n"


def _short_summary(text: str, max_words: int = 10, max_chars: int = 80) -> str:
    words = [part for part in text.strip().split() if part]
    if not words:
        return ""
    summary = " ".join(words[:max_words])
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "…"
    return summary


def _compact_whitespace(text: str) -> str:
    return " ".join(str(text or "").split())


def _strip_ansi_stream(carry: str, text: str) -> tuple[str, str]:
    source = f"{carry}{text}"
    if not source:
        return "", ""

    output: list[str] = []
    idx = 0
    length = len(source)
    while idx < length:
        char = source[idx]
        if char != "\x1b":
            output.append(char)
            idx += 1
            continue

        seq_start = idx
        idx += 1
        if idx >= length:
            return "".join(output), source[seq_start:]

        marker = source[idx]
        if marker == "[":
            idx += 1
            while idx < length:
                final = source[idx]
                if "@" <= final <= "~":
                    idx += 1
                    break
                idx += 1
            else:
                return "".join(output), source[seq_start:]
            continue

        if marker in {"]", "P"}:
            idx += 1
            terminated = False
            while idx < length:
                current = source[idx]
                if current == "\x07":
                    idx += 1
                    terminated = True
                    break
                if current == "\x1b":
                    if idx + 1 >= length:
                        return "".join(output), source[seq_start:]
                    if source[idx + 1] == "\\":
                        idx += 2
                        terminated = True
                        break
                idx += 1
            if not terminated:
                return "".join(output), source[seq_start:]
            continue

        idx += 1

    return "".join(output), ""


def _sanitize_submitted_prompt(prompt: Any) -> str:
    cleaned = _compact_whitespace(prompt).strip()
    if not cleaned:
        return ""
    cleaned = OSC_COLOR_RESPONSE_FRAGMENT_RE.sub(" ", cleaned)
    cleaned = _compact_whitespace(cleaned).strip(" ;")
    return cleaned


def _looks_like_terminal_control_payload(text: str) -> bool:
    value = _compact_whitespace(text).strip()
    if not value:
        return False
    lowered = value.lower()
    if re.match(r"^\]?\d{1,3};(?:rgb|rgba):[0-9a-f]{2,4}/[0-9a-f]{2,4}/[0-9a-f]{2,4}", lowered):
        return True
    if re.match(r"^\]?\d{1,3};", lowered) and "rgb:" in lowered:
        return True
    return False


def _truncate_title(text: str, max_chars: int) -> str:
    cleaned = _compact_whitespace(text).strip()
    if not cleaned or max_chars <= 0:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    for delimiter in (" -- ", " - ", " | ", ": ", "; ", ". ", ", "):
        head = cleaned.split(delimiter, 1)[0].strip()
        if 12 <= len(head) <= max_chars:
            cleaned = head
            break
    if len(cleaned) <= max_chars:
        return cleaned

    words = cleaned.split()
    kept: list[str] = []
    for word in words:
        next_words = [*kept, word]
        joined = " ".join(next_words).strip()
        if len(joined) + 1 > max_chars:
            break
        kept.append(word)
    if kept:
        truncated = " ".join(kept).rstrip(" ,;:-")
        return f"{truncated}…" if len(truncated) < len(cleaned) else truncated

    if max_chars == 1:
        return "…"
    return cleaned[: max_chars - 1].rstrip() + "…"


def _chat_display_name(chat_name: Any) -> str:
    cleaned = _compact_whitespace(str(chat_name or "")).strip()
    if not cleaned:
        return CHAT_DEFAULT_NAME
    if CHAT_AUTOGENERATED_NAME_RE.fullmatch(cleaned):
        return CHAT_DEFAULT_NAME
    return cleaned


def _new_artifact_publish_token() -> str:
    return secrets.token_hex(24)


def _hash_artifact_publish_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_agent_tools_token() -> str:
    return secrets.token_hex(24)


def _hash_agent_tools_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_ready_ack_guid() -> str:
    return uuid.uuid4().hex


def _normalize_ready_ack_stage(value: Any) -> str:
    candidate = _compact_whitespace(str(value or "")).strip().lower()
    if candidate not in SUPPORTED_AGENT_READY_ACK_STAGES:
        return AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED
    return candidate


def _normalize_artifact_name(value: Any, fallback: str = "") -> str:
    candidate = _compact_whitespace(str(value or "")).strip()
    if not candidate:
        candidate = _compact_whitespace(str(fallback or "")).strip()
    if not candidate:
        candidate = "artifact"
    if len(candidate) > CHAT_ARTIFACT_NAME_MAX_CHARS:
        candidate = candidate[: CHAT_ARTIFACT_NAME_MAX_CHARS - 1].rstrip() + "…"
    return candidate


def _coerce_artifact_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or len(text) > CHAT_ARTIFACT_PATH_MAX_CHARS:
        return ""

    parts: list[str] = []
    for raw_part in text.split("/"):
        part = raw_part.strip()
        if not part or part == ".":
            continue
        if part == "..":
            return ""
        parts.append(part)
    if not parts:
        return ""
    return "/".join(parts)


def _normalize_chat_artifacts(raw_artifacts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_artifacts, list):
        return []

    entries: list[dict[str, Any]] = []
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            continue
        artifact_id = str(raw_artifact.get("id") or "").strip()
        relative_path = _coerce_artifact_relative_path(raw_artifact.get("relative_path"))
        if not artifact_id or not relative_path:
            continue
        storage_relative_path = _coerce_artifact_relative_path(raw_artifact.get("storage_relative_path"))
        size_raw = raw_artifact.get("size_bytes")
        try:
            size_bytes = int(size_raw)
        except (TypeError, ValueError):
            size_bytes = 0
        if size_bytes < 0:
            size_bytes = 0
        entries.append(
            {
                "id": artifact_id,
                "name": _normalize_artifact_name(raw_artifact.get("name"), fallback=Path(relative_path).name),
                "relative_path": relative_path,
                "storage_relative_path": storage_relative_path,
                "size_bytes": size_bytes,
                "created_at": str(raw_artifact.get("created_at") or ""),
            }
        )
    return entries[-CHAT_ARTIFACTS_MAX_ITEMS:]


def _normalize_chat_current_artifact_ids(raw_ids: Any, artifacts: list[dict[str, Any]]) -> list[str]:
    if not isinstance(raw_ids, list):
        return []
    known_ids = {str(artifact.get("id") or "") for artifact in artifacts}
    normalized: list[str] = []
    for raw_id in raw_ids:
        artifact_id = str(raw_id or "").strip()
        if not artifact_id or artifact_id in normalized:
            continue
        if artifact_id not in known_ids:
            continue
        normalized.append(artifact_id)
    return normalized[-CHAT_ARTIFACTS_MAX_ITEMS:]


def _normalize_chat_artifact_prompt_history(raw_history: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_history, list):
        return []
    entries: list[dict[str, Any]] = []
    for raw_entry in raw_history:
        if not isinstance(raw_entry, dict):
            continue
        prompt = _sanitize_submitted_prompt(raw_entry.get("prompt"))
        if not prompt:
            continue
        if len(prompt) > CHAT_ARTIFACT_PROMPT_LABEL_MAX_CHARS:
            prompt = prompt[:CHAT_ARTIFACT_PROMPT_LABEL_MAX_CHARS].rstrip()
        artifacts = _normalize_chat_artifacts(raw_entry.get("artifacts"))
        if not artifacts:
            continue
        entries.append(
            {
                "prompt": prompt,
                "archived_at": str(raw_entry.get("archived_at") or ""),
                "artifacts": artifacts,
            }
        )
    return entries[-CHAT_ARTIFACT_PROMPT_HISTORY_MAX_ITEMS:]


def _chat_preview_candidates_from_log(log_path: Path) -> tuple[list[str], list[str]]:
    lines = _chat_preview_lines_from_log(log_path)
    if not lines:
        return [], []

    user_candidates: list[str] = []
    assistant_candidates: list[str] = []
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        if line_clean.startswith(("›", ">", "You:")):
            normalized = line_clean.lstrip("›>").strip()
            if normalized.lower().startswith("you:"):
                normalized = normalized[4:].strip()
            if normalized:
                user_candidates.append(normalized)
            continue
        if line_clean.startswith("Tip:"):
            continue
        assistant_candidates.append(line_clean)
    return user_candidates, assistant_candidates


def _read_chat_log_preview(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    with log_path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        size = log_file.tell()
        start = size - CHAT_PREVIEW_LOG_MAX_BYTES if size > CHAT_PREVIEW_LOG_MAX_BYTES else 0
        log_file.seek(start)
        return log_file.read().decode("utf-8", errors="ignore")


def _sanitize_terminal_log_text(raw_text: str) -> str:
    text = str(raw_text or "")
    # Cursor jumps / erase-in-line updates are common in animated terminal output.
    # Treat them as logical line boundaries so adjacent frames do not collapse.
    text = ANSI_CURSOR_POSITION_RE.sub("\n", text)
    text = ANSI_ERASE_IN_LINE_RE.sub("\n", text)
    text, _ = _strip_ansi_stream("", text)
    # Preserve carriage-return boundaries from animated terminal updates.
    text = text.replace("\r", "\n")
    text = TERMINAL_CONTROL_CHAR_RE.sub("", text)
    text = OSC_COLOR_RESPONSE_FRAGMENT_RE.sub(" ", text)
    return text


def _chat_preview_lines_from_log(log_path: Path) -> list[str]:
    raw = _read_chat_log_preview(log_path)
    if not raw:
        return []
    text = _sanitize_terminal_log_text(raw)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _openai_generate_chat_title(
    api_key: str,
    user_prompts: list[str],
    max_chars: int = CHAT_TITLE_MAX_CHARS,
    model: str = CHAT_TITLE_OPENAI_MODEL,
    timeout_seconds: float = CHAT_TITLE_API_TIMEOUT_SECONDS,
) -> str:
    prompts = _normalize_chat_prompt_history(user_prompts)
    if not api_key:
        raise RuntimeError("OpenAI API key is not configured for chat title generation.")
    if not prompts:
        raise RuntimeError("No submitted user prompts are available for chat title generation.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI Python SDK is not installed. Add dependency 'openai>=1.0'.") from exc

    instructions = _render_prompt_template(
        PROMPT_CHAT_TITLE_OPENAI_SYSTEM_FILE,
        max_chars=max_chars,
    )
    prompt_lines = "\n".join(f"{index + 1}. {value}" for index, value in enumerate(prompts))
    user_prompt = _render_prompt_template(
        PROMPT_CHAT_TITLE_OPENAI_USER_FILE,
        prompt_lines=prompt_lines,
        max_chars=max_chars,
    )
    try:
        client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        completion = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=64,
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI chat title request failed: {exc}") from exc

    choices = getattr(completion, "choices", None)
    if not choices:
        raise RuntimeError("OpenAI returned no title choices.")
    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    content = getattr(message, "content", "") if message is not None else ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text_value = getattr(item, "text", None)
            if text_value:
                parts.append(str(text_value))
        normalized = "".join(parts).strip()
    else:
        normalized = str(content or "").strip()
    if not normalized:
        raise RuntimeError("OpenAI returned an empty title.")
    first_line = normalized.splitlines()[0].strip().strip("\"'`")
    title = _truncate_title(first_line, max_chars)
    if not title:
        raise RuntimeError("OpenAI returned an invalid chat title.")
    return title


def _resolve_codex_executable(host_codex_dir: Path) -> str:
    bundled = host_codex_dir / "bin" / "codex"
    if bundled.is_file():
        return str(bundled)
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    raise RuntimeError("Codex CLI is not installed. ChatGPT account title generation is unavailable.")


def _codex_exec_error_message(output_text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", str(output_text or "")).replace("\r", "\n")
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return "Unknown error."

    for line in reversed(lines):
        if line.lower().startswith("error:"):
            detail = line.split(":", 1)[1].strip()
            if detail:
                return _short_summary(detail, max_words=30, max_chars=220)
    return _short_summary(lines[-1], max_words=30, max_chars=220)


def _codex_exec_error_message_full(output_text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", str(output_text or "")).replace("\r", "\n")
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return "Unknown error."
    for line in reversed(lines):
        if line.lower().startswith("error:"):
            detail = line.split(":", 1)[1].strip()
            if detail:
                return detail
    return lines[-1]


def _codex_generate_chat_title(
    host_agent_home: Path,
    host_codex_dir: Path,
    user_prompts: list[str],
    max_chars: int = CHAT_TITLE_MAX_CHARS,
    timeout_seconds: float = CHAT_TITLE_CODEX_TIMEOUT_SECONDS,
) -> str:
    prompts = _normalize_chat_prompt_history(user_prompts)
    if not prompts:
        raise RuntimeError("No submitted user prompts are available for chat title generation.")

    codex_exec = _resolve_codex_executable(host_codex_dir)
    prompt_lines = "\n".join(f"{index + 1}. {value}" for index, value in enumerate(prompts))
    request_prompt = _render_prompt_template(
        PROMPT_CHAT_TITLE_CODEX_REQUEST_FILE,
        max_chars=max_chars,
        prompt_lines=prompt_lines,
    )
    output_file = host_codex_dir / f"title-summary-{uuid.uuid4().hex}.txt"

    env = os.environ.copy()
    env["HOME"] = str(host_agent_home)
    env["CODEX_HOME"] = str(host_codex_dir)

    cmd = [
        codex_exec,
        "exec",
        "--skip-git-repo-check",
        "--cd",
        str(_repo_root()),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(output_file),
        request_prompt,
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=True,
            env=env,
            timeout=max(1.0, float(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ChatGPT account title request timed out.") from exc

    output_text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        try:
            output_file.unlink()
        except OSError:
            pass
        detail = _codex_exec_error_message(output_text)
        raise RuntimeError(f"ChatGPT account title request failed: {detail}")

    try:
        raw_title = output_file.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError as exc:
        raise RuntimeError("ChatGPT account title request returned no title output.") from exc
    finally:
        try:
            output_file.unlink()
        except OSError:
            pass

    if not raw_title:
        raise RuntimeError("ChatGPT account title request returned an empty title.")
    first_line = raw_title.splitlines()[0].strip().strip("\"'`")
    title = _truncate_title(first_line, max_chars)
    if not title:
        raise RuntimeError("ChatGPT account title request returned an invalid title.")
    return title


def _parse_json_object_from_text(raw_text: Any) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("empty payload")

    candidates = [text]
    if text.startswith("```"):
        without_fence = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        without_fence = re.sub(r"\s*```\s*$", "", without_fence)
        if without_fence.strip():
            candidates.append(without_fence.strip())

    for candidate in candidates:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            continue
        idx = 0
        while True:
            start = candidate_text.find("{", idx)
            if start < 0:
                break
            try:
                parsed, _end = json.JSONDecoder().raw_decode(candidate_text, start)
            except json.JSONDecodeError:
                idx = start + 1
                continue
            if isinstance(parsed, dict):
                return parsed
            idx = start + 1
    raise ValueError("invalid json object")


def _json_payload_preview(raw_body: bytes, *, max_bytes: int = 160) -> str:
    clipped = raw_body[:max_bytes]
    return clipped.hex()


def _is_json_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").strip().lower()
    return normalized == "application/json" or normalized.endswith("+json") or normalized == "text/json"


def _artifact_upload_name(request: Request, *, fallback: str) -> str:
    requested_name = (
        str(request.headers.get("x-agent-hub-artifact-name") or request.query_params.get("name") or "").strip()
    )
    if not requested_name:
        content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type:
            extension = mimetypes.guess_extension(content_type) or ""
            requested_name = f"{fallback}{extension}"
        else:
            requested_name = str(fallback)
    requested_name = _normalize_artifact_name(requested_name, fallback=fallback)
    if not requested_name:
        requested_name = str(fallback)

    safe_name = Path(requested_name).name
    return _normalize_artifact_name(safe_name, fallback=fallback)


def _write_artifact_upload_to_workspace(
    workspace: Path,
    raw_body: bytes,
    *,
    requested_name: str,
    context: str,
) -> tuple[Path, str]:
    uploads_root = (workspace / ".agent-hub-artifacts").resolve()
    try:
        uploads_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to prepare artifact upload staging directory.") from exc

    normalized_name = _normalize_artifact_name(requested_name, fallback="artifact")
    if not normalized_name:
        normalized_name = "artifact"
    normalized_name = Path(normalized_name).name
    if not normalized_name:
        normalized_name = "artifact"

    normalized_name = _normalize_artifact_name(normalized_name, fallback="artifact")
    staged_path = uploads_root / f"{uuid.uuid4().hex}-{normalized_name}"
    try:
        staged_path.write_bytes(raw_body)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to persist uploaded artifact payload to chat workspace.",
        ) from exc
    LOGGER.info("Staged binary artifact payload for %s to %s", context, staged_path)
    return staged_path.resolve(), str(normalized_name)


async def _parse_artifact_request_payload(
    request: Request,
    *,
    context: str,
    workspace: Path,
) -> tuple[dict[str, Any], list[Path]]:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type == "multipart/form-data":
        form = await request.form()
        upload: UploadFile | None = None
        if isinstance(form.get("file"), UploadFile):
            upload = form.get("file")  # type: ignore[assignment]
        else:
            for value in form.values():
                if isinstance(value, UploadFile):
                    upload = value
                    break
        if upload is None:
            LOGGER.warning("Multipart artifact payload missing file for %s", context)
            raise HTTPException(status_code=400, detail="Multipart payload must include a file field.")

        raw_body = await upload.read()
        requested_name = str(form.get("name") or "").strip()
        if not requested_name:
            requested_name = _normalize_artifact_name(upload.filename, fallback=_artifact_upload_name(request, fallback="artifact"))
        uploaded_path, uploaded_name = _write_artifact_upload_to_workspace(
            workspace,
            raw_body,
            requested_name=requested_name,
            context=context,
        )
        return {"path": str(uploaded_path), "name": uploaded_name}, [uploaded_path]

    raw_body = await request.body()
    if not raw_body:
        if _is_json_content_type(content_type):
            LOGGER.warning("Invalid JSON payload for %s: empty body.", context)
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        LOGGER.warning("Empty artifact payload for %s", context)
        raise HTTPException(status_code=400, detail="Artifact payload is empty.")

    if _is_json_content_type(content_type):
        try:
            payload = json.loads(raw_body)
        except UnicodeDecodeError as exc:
            LOGGER.warning(
                "Invalid UTF-8 JSON payload for %s (body_bytes=%s): %s",
                context,
                _json_payload_preview(raw_body),
                exc,
            )
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
        except json.JSONDecodeError as exc:
            LOGGER.warning(
                "Invalid JSON payload for %s (body_bytes=%s): %s",
                context,
                _json_payload_preview(raw_body),
                exc,
            )
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
        if not isinstance(payload, dict):
            LOGGER.warning(
                "Invalid JSON payload for %s: expected object, got %s. body_bytes=%s",
                context,
                type(payload).__name__,
                _json_payload_preview(raw_body),
            )
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return payload, []

    artifact_name = _artifact_upload_name(request, fallback="artifact")
    uploaded_path, uploaded_name = _write_artifact_upload_to_workspace(
        workspace,
        raw_body,
        requested_name=artifact_name,
        context=context,
    )
    return {"path": str(uploaded_path), "name": uploaded_name}, [uploaded_path]


def _cleanup_uploaded_artifact_paths(uploaded_paths: list[Path]) -> None:
    for uploaded_path in uploaded_paths:
        try:
            uploaded_path.unlink()
        except OSError:
            continue


def _normalize_chat_prompt_history(user_prompts: list[str]) -> list[str]:
    normalized = [
        _compact_whitespace(prompt).strip()
        for prompt in user_prompts
        if _compact_whitespace(prompt).strip() and not _looks_like_terminal_control_payload(_compact_whitespace(prompt).strip())
    ]
    if not normalized:
        return []
    return normalized


def _chat_title_prompt_fingerprint(user_prompts: list[str], max_chars: int = CHAT_TITLE_MAX_CHARS) -> str:
    prompts = _normalize_chat_prompt_history(user_prompts)
    if not prompts:
        return ""
    fingerprint_payload = {
        "model": CHAT_TITLE_OPENAI_MODEL,
        "max_chars": max_chars,
        "prompts": prompts,
    }
    serialized = json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _append_tail(existing: str, chunk: str, max_chars: int) -> str:
    merged = (existing or "") + (chunk or "")
    if len(merged) <= max_chars:
        return merged
    return merged[-max_chars:]


def _clean_url_token(url_text: str) -> str:
    cleaned = str(url_text or "").strip()
    cleaned = cleaned.strip("<>")
    cleaned = cleaned.rstrip(".,);]}>\"'")
    return cleaned


def _first_url_in_text(text: str, starts_with: str) -> str:
    if not text:
        return ""
    pattern = rf"{re.escape(starts_with)}[^\s]+"
    match = re.search(pattern, text)
    return _clean_url_token(match.group(0)) if match else ""


def _openai_login_url_in_text(text: str) -> str:
    if not text:
        return ""
    for raw_match in re.finditer(r"https://[^\s]+", text):
        candidate = _clean_url_token(raw_match.group(0))
        if not candidate:
            continue
        parsed = urllib.parse.urlparse(candidate)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            continue
        query = urllib.parse.parse_qs(parsed.query or "")
        redirect_values = query.get("redirect_uri") or []
        for redirect_value in redirect_values:
            local_callback_url, _port, _path = _parse_local_callback(redirect_value)
            if local_callback_url:
                return candidate
        if host in {"auth.openai.com", "auth.chatgpt.com"}:
            return candidate
        if host in {"chatgpt.com", "www.chatgpt.com"}:
            normalized_path = (parsed.path or "").strip().lower()
            if any(marker in normalized_path for marker in ("/auth", "/oauth", "/login")):
                return candidate
    return ""


def _parse_local_callback(url_text: str) -> tuple[str, int, str]:
    cleaned = _clean_url_token(url_text)
    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.scheme.startswith("http"):
        return "", 0, ""
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1"}:
        return "", 0, ""
    callback_path = parsed.path or "/auth/callback"
    callback_port = OPENAI_ACCOUNT_LOGIN_DEFAULT_CALLBACK_PORT
    try:
        parsed_port = parsed.port
    except ValueError:
        parsed_port = None
        port_match = re.search(r":(\d+)", parsed.netloc or "")
        if port_match:
            try:
                parsed_port = int(port_match.group(1))
            except ValueError:
                parsed_port = None
    if parsed_port is not None:
        callback_port = parsed_port
    if callback_port < 1 or callback_port > 65535:
        return "", 0, ""

    normalized_netloc = host
    if callback_port != OPENAI_ACCOUNT_LOGIN_DEFAULT_CALLBACK_PORT or ":" in (parsed.netloc or ""):
        normalized_netloc = f"{host}:{callback_port}"
    normalized_url = urllib.parse.urlunparse(
        (
            parsed.scheme or "http",
            normalized_netloc,
            callback_path,
            "",
            parsed.query,
            parsed.fragment,
        )
    )
    return normalized_url, callback_port, callback_path


def _normalize_callback_forward_host(raw_value: Any) -> str:
    token = str(raw_value or "").strip().lower().strip("[]")
    if not token:
        return ""
    if any(marker in token for marker in ("/", "?", "#", "@", " ")):
        return ""
    if ":" in token:
        try:
            ipaddress.IPv6Address(token)
        except ValueError:
            return ""
        return token
    if re.fullmatch(r"[a-z0-9.-]+", token):
        return token
    return ""


def _parse_callback_forward_host_port(raw_value: Any) -> tuple[str, int | None]:
    token = str(raw_value or "").strip()
    if not token:
        return "", None
    if "," in token:
        token = token.split(",", 1)[0].strip()
    if not token:
        return "", None

    host_token = token
    parsed_port: int | None = None
    if token.startswith("["):
        bracket_end = token.find("]")
        if bracket_end > 0:
            host_token = token[1:bracket_end]
            remainder = token[bracket_end + 1 :].strip()
            if remainder.startswith(":") and remainder[1:].isdigit():
                parsed_port = int(remainder[1:])
        else:
            host_token = token.strip("[]")
    else:
        if token.count(":") == 1:
            maybe_host, maybe_port = token.rsplit(":", 1)
            if maybe_port.isdigit():
                host_token = maybe_host
                parsed_port = int(maybe_port)

    normalized_host = _normalize_callback_forward_host(host_token)
    if not normalized_host:
        return "", None
    if parsed_port is not None and (parsed_port < 1 or parsed_port > 65535):
        parsed_port = None
    return normalized_host, parsed_port


def _parse_forwarded_header(raw_value: Any) -> dict[str, str]:
    token = str(raw_value or "").strip()
    if not token:
        return {}
    first_entry = token.split(",", 1)[0].strip()
    if not first_entry:
        return {}
    parsed: dict[str, str] = {}
    for segment in first_entry.split(";"):
        key, sep, value = segment.partition("=")
        if not sep:
            continue
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        normalized_value = str(value or "").strip().strip('"')
        if normalized_value:
            parsed[normalized_key] = normalized_value
    return parsed


def _openai_callback_request_context_from_request(request: Request) -> dict[str, Any]:
    headers = request.headers
    forwarded_raw = str(headers.get("forwarded") or "").strip()
    forwarded_values = _parse_forwarded_header(forwarded_raw)
    x_forwarded_host_raw = str(headers.get("x-forwarded-host") or "").strip()
    x_forwarded_proto_raw = str(headers.get("x-forwarded-proto") or "").strip().lower()
    x_forwarded_port_raw = str(headers.get("x-forwarded-port") or "").strip()
    host_header_raw = str(headers.get("host") or "").strip()
    client_host = request.client.host if request.client is not None else ""

    x_forwarded_host, x_forwarded_host_port = _parse_callback_forward_host_port(x_forwarded_host_raw)
    forwarded_host, forwarded_host_port = _parse_callback_forward_host_port(forwarded_values.get("host") or "")
    host_header_host, host_header_port = _parse_callback_forward_host_port(host_header_raw)
    parsed_request_client_host, _ = _parse_callback_forward_host_port(client_host)

    parsed_x_forwarded_port: int | None = None
    if x_forwarded_port_raw.isdigit():
        port_value = int(x_forwarded_port_raw)
        if 1 <= port_value <= 65535:
            parsed_x_forwarded_port = port_value

    return {
        "client_host": parsed_request_client_host,
        "forwarded_raw_present": bool(forwarded_raw),
        "forwarded_host": forwarded_host,
        "forwarded_host_port": forwarded_host_port,
        "forwarded_proto": str(forwarded_values.get("proto") or "").strip().lower(),
        "x_forwarded_host": x_forwarded_host,
        "x_forwarded_host_port": x_forwarded_host_port,
        "x_forwarded_proto": x_forwarded_proto_raw.split(",", 1)[0].strip(),
        "x_forwarded_port": parsed_x_forwarded_port,
        "host_header_host": host_header_host,
        "host_header_port": host_header_port,
    }


def _openai_callback_query_summary(query: str) -> dict[str, Any]:
    keys: list[str] = []
    sensitive_keys: list[str] = []
    for key, _value in urllib.parse.parse_qsl(query or "", keep_blank_values=True):
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        keys.append(normalized_key)
        lowered = normalized_key.lower()
        if (
            lowered in OPENAI_ACCOUNT_CALLBACK_SENSITIVE_QUERY_KEYS
            or "token" in lowered
            or "secret" in lowered
            or "verifier" in lowered
        ):
            sensitive_keys.append(normalized_key)
    return {
        "param_count": len(keys),
        "keys": keys,
        "sensitive_keys": sorted(set(sensitive_keys)),
        "values_redacted": True,
    }


def _redact_url_query_values(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or ""))
    if not parsed.query:
        return str(url or "")
    redacted_pairs: list[tuple[str, str]] = []
    for key, _value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        redacted_pairs.append((str(key or ""), "<redacted>"))
    redacted_query = urllib.parse.urlencode(redacted_pairs, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, parsed.fragment))


def _discover_linux_default_gateway_host() -> tuple[str, dict[str, str]]:
    diagnostics: dict[str, str] = {}
    route_file = Path("/proc/net/route")
    if not route_file.exists():
        diagnostics["status"] = "missing_route_file"
        return "", diagnostics
    try:
        lines = route_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        diagnostics["status"] = "route_read_error"
        diagnostics["error"] = f"{type(exc).__name__}: {exc}"
        return "", diagnostics

    for line in lines[1:]:
        columns = line.split()
        if len(columns) < 4:
            continue
        iface = columns[0]
        destination = columns[1]
        gateway_hex = columns[2]
        flags_hex = columns[3]
        try:
            flags = int(flags_hex, 16)
        except ValueError:
            continue
        if destination != "00000000" or (flags & 0x2) == 0:
            continue
        try:
            gateway = socket.inet_ntoa(struct.pack("<L", int(gateway_hex, 16)))
        except (ValueError, OSError):
            continue
        normalized_gateway = _normalize_callback_forward_host(gateway)
        if normalized_gateway:
            diagnostics["status"] = "resolved"
            diagnostics["interface"] = iface
            diagnostics["gateway"] = normalized_gateway
            return normalized_gateway, diagnostics

    diagnostics["status"] = "not_found"
    return "", diagnostics


def _discover_docker_bridge_gateway_host() -> tuple[str, dict[str, str]]:
    diagnostics: dict[str, str] = {"status": "not_attempted"}
    if shutil.which("docker") is None:
        diagnostics["status"] = "docker_unavailable"
        return "", diagnostics
    try:
        process = subprocess.run(
            ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=OPENAI_ACCOUNT_CALLBACK_DOCKER_INSPECT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        diagnostics["status"] = "docker_inspect_error"
        diagnostics["error"] = f"{type(exc).__name__}: {exc}"
        return "", diagnostics

    stdout = str(process.stdout or "").strip()
    stderr = str(process.stderr or "").strip()
    diagnostics["status"] = "docker_inspect_complete"
    diagnostics["return_code"] = str(int(process.returncode))
    if stderr:
        diagnostics["stderr"] = stderr[:220]
    if process.returncode != 0:
        return "", diagnostics
    normalized_gateway = _normalize_callback_forward_host(stdout)
    if not normalized_gateway:
        diagnostics["status"] = "docker_inspect_empty_gateway"
        return "", diagnostics
    diagnostics["status"] = "resolved"
    diagnostics["gateway"] = normalized_gateway
    return normalized_gateway, diagnostics


def _discover_openai_callback_bridge_hosts() -> tuple[list[str], dict[str, Any]]:
    hosts: list[str] = []
    linux_gateway, linux_diagnostics = _discover_linux_default_gateway_host()
    docker_gateway, docker_diagnostics = _discover_docker_bridge_gateway_host()
    if docker_gateway and docker_gateway not in hosts:
        hosts.append(docker_gateway)
    return hosts, {
        "linux_default_route": linux_diagnostics,
        "docker_bridge": docker_diagnostics,
        "bridge_hosts": hosts,
    }


def _classify_openai_callback_forward_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "timeout"
        if isinstance(reason, socket.timeout):
            return "timeout"
        if isinstance(reason, ConnectionRefusedError):
            return "connection_refused"
        if isinstance(reason, socket.gaierror):
            return "dns_resolution_failed"
        if isinstance(reason, OSError):
            if reason.errno in {101, 113}:
                return "network_unreachable"
            if reason.errno == 111:
                return "connection_refused"
        reason_text = str(reason or "").strip().lower()
        if "timed out" in reason_text:
            return "timeout"
        if "refused" in reason_text:
            return "connection_refused"
        if "name or service not known" in reason_text or "temporary failure in name resolution" in reason_text:
            return "dns_resolution_failed"
        return "url_error"
    if isinstance(exc, OSError):
        if exc.errno in {101, 113}:
            return "network_unreachable"
        if exc.errno == 111:
            return "connection_refused"
        return "os_error"
    return "unknown_transport_error"


def _forward_openai_callback_via_container_loopback(
    container_name: str,
    callback_port: int,
    callback_path: str,
    query: str,
) -> OpenAICallbackContainerForwardResult:
    if not container_name:
        return OpenAICallbackContainerForwardResult(attempted=False)
    if shutil.which("docker") is None:
        return OpenAICallbackContainerForwardResult(
            attempted=False,
            error_class="docker_unavailable",
            error_detail="docker command not found",
        )

    python_script = (
        "import json, os, urllib.error, urllib.request\n"
        "port = int(os.environ.get('AGENT_HUB_CALLBACK_PORT', '1455'))\n"
        "path = os.environ.get('AGENT_HUB_CALLBACK_PATH', '/auth/callback')\n"
        "query = os.environ.get('AGENT_HUB_CALLBACK_QUERY', '')\n"
        "timeout = max(0.5, float(os.environ.get('AGENT_HUB_CALLBACK_TIMEOUT', '8.0')))\n"
        "url = f'http://127.0.0.1:{port}{path}'\n"
        "if query:\n"
        "    url = f'{url}?{query}'\n"
        "status = 0\n"
        "body = ''\n"
        "try:\n"
        "    with urllib.request.urlopen(url, timeout=timeout) as response:\n"
        "        status = int(response.getcode() or 0)\n"
        "        body = response.read().decode('utf-8', errors='ignore')\n"
        "except urllib.error.HTTPError as exc:\n"
        "    status = int(exc.code or 0)\n"
        "    body = exc.read().decode('utf-8', errors='ignore')\n"
        "print(json.dumps({'status_code': status, 'body': body}))\n"
    )
    launch_script = (
        "if command -v python3 >/dev/null 2>&1; then "
        "exec python3 -c \"$AGENT_HUB_CALLBACK_FORWARDER_SCRIPT\"; "
        "elif command -v python >/dev/null 2>&1; then "
        "exec python -c \"$AGENT_HUB_CALLBACK_FORWARDER_SCRIPT\"; "
        "else "
        "echo 'python runtime unavailable in login container' >&2; "
        "exit 127; "
        "fi"
    )
    cmd = [
        "docker",
        "exec",
        "--env",
        f"AGENT_HUB_CALLBACK_PORT={int(callback_port)}",
        "--env",
        f"AGENT_HUB_CALLBACK_PATH={callback_path}",
        "--env",
        f"AGENT_HUB_CALLBACK_QUERY={query}",
        "--env",
        f"AGENT_HUB_CALLBACK_TIMEOUT={OPENAI_ACCOUNT_CALLBACK_FORWARD_TIMEOUT_SECONDS}",
        "--env",
        f"AGENT_HUB_CALLBACK_FORWARDER_SCRIPT={python_script}",
        container_name,
        "sh",
        "-lc",
        launch_script,
    ]
    try:
        process = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(2.0, OPENAI_ACCOUNT_CALLBACK_FORWARD_TIMEOUT_SECONDS + 2.0),
        )
    except subprocess.TimeoutExpired as exc:
        return OpenAICallbackContainerForwardResult(
            attempted=True,
            error_class="container_exec_timeout",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    except OSError as exc:
        return OpenAICallbackContainerForwardResult(
            attempted=True,
            error_class="container_exec_os_error",
            error_detail=f"{type(exc).__name__}: {exc}",
        )

    if process.returncode != 0:
        stdout = str(process.stdout or "").strip()
        stderr = str(process.stderr or "").strip()
        combined = f"{stdout}\n{stderr}".lower()
        error_detail = (
            f"rc={int(process.returncode)} "
            f"stdout={stdout[:220] if stdout else '<empty>'} "
            f"stderr={stderr[:220] if stderr else '<empty>'}"
        )
        if "not running" in combined or "no such container" in combined:
            return OpenAICallbackContainerForwardResult(
                attempted=True,
                error_class="container_not_running",
                error_detail=error_detail,
            )
        if process.returncode == 127 or "python runtime unavailable in login container" in combined:
            return OpenAICallbackContainerForwardResult(
                attempted=True,
                error_class="container_python_missing",
                error_detail=error_detail,
            )
        return OpenAICallbackContainerForwardResult(
            attempted=True,
            error_class="container_exec_failed",
            error_detail=error_detail,
        )

    stdout = str(process.stdout or "").strip()
    if not stdout:
        return OpenAICallbackContainerForwardResult(
            attempted=True,
            error_class="container_exec_empty_output",
            error_detail="empty stdout",
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return OpenAICallbackContainerForwardResult(
            attempted=True,
            error_class="container_exec_invalid_output",
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    if not isinstance(payload, dict):
        return OpenAICallbackContainerForwardResult(
            attempted=True,
            error_class="container_exec_invalid_output",
            error_detail="stdout payload is not object",
        )
    status_code = int(payload.get("status_code") or 0)
    response_body = str(payload.get("body") or "")
    return OpenAICallbackContainerForwardResult(
        attempted=True,
        ok=True,
        status_code=status_code,
        response_body=response_body,
    )


def _host_port_netloc(host: str, port: int) -> str:
    normalized_host = str(host or "").strip()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return f"{normalized_host}:{int(port)}"


def _chat_subtitle_from_log(log_path: Path) -> str:
    lines = _chat_preview_lines_from_log(log_path)
    if not lines:
        return ""

    def normalize_candidate_line(raw_line: str) -> str:
        candidate = str(raw_line or "").strip()
        if not candidate:
            return ""
        candidate = LEADING_INVISIBLE_RE.sub("", candidate).strip()
        while candidate and candidate[0] in "│┃┆┊╎╏":
            candidate = candidate[1:].lstrip()
        return candidate

    def strip_known_marker_prefix(candidate: str) -> str:
        for marker in CHAT_SUBTITLE_MARKERS:
            if candidate.startswith(marker):
                return _compact_whitespace(candidate[len(marker) :]).strip()
        return _compact_whitespace(candidate).strip()

    def strip_status_prefix(candidate: str) -> str:
        value = _compact_whitespace(candidate).strip()
        if not value:
            return ""
        index = 0
        while index < len(value):
            ch = value[index]
            if ch.isspace() or ch in "./|\\-":
                index += 1
                continue
            codepoint = ord(ch)
            if ch in CHAT_SUBTITLE_MARKERS:
                index += 1
                continue
            if (
                codepoint == 0x2219
                or 0x2022 <= codepoint <= 0x2043
                or 0x25A0 <= codepoint <= 0x25FF
            ):
                index += 1
                continue
            if 0x2800 <= codepoint <= 0x28FF:  # braille spinner glyphs
                index += 1
                continue
            break
        return _compact_whitespace(value[index:]).strip()

    def subtitle_value(line: str) -> str:
        candidate = normalize_candidate_line(line)
        if not candidate:
            return ""
        if candidate.startswith((">", "›")):
            return ""
        if candidate.lower().startswith("you:"):
            return ""
        compact = _compact_whitespace(candidate).strip()
        if not compact:
            return ""
        lowered = compact.lower()
        if "waiting for background terminal" in lowered:
            return strip_status_prefix(compact) or strip_known_marker_prefix(compact)
        if "esc to interrupt" in lowered and "working (" in lowered:
            return strip_status_prefix(compact) or compact
        for marker in CHAT_SUBTITLE_MARKERS:
            if compact.startswith(marker):
                return _compact_whitespace(compact[len(marker) :]).strip()
        candidate = compact
        first = candidate[0]
        remainder = _compact_whitespace(candidate[1:]).strip()
        if not remainder:
            return ""
        if not any(ch.isalpha() for ch in remainder):
            return ""
        marker_codepoint = ord(first)
        if (
            marker_codepoint == 0x2219  # BULLET OPERATOR
            or 0x2022 <= marker_codepoint <= 0x2043  # bullets and related punctuation
            or 0x25A0 <= marker_codepoint <= 0x25FF  # geometric shapes
            or 0x2800 <= marker_codepoint <= 0x28FF  # braille spinner glyphs
        ):
            return remainder
        return ""

    prompt_index = -1
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].startswith((">", "›")):
            prompt_index = index
            break

    search_start = prompt_index - 1 if prompt_index >= 0 else len(lines) - 1
    for index in range(search_start, -1, -1):
        subtitle = subtitle_value(lines[index])
        if subtitle:
            if len(subtitle) > CHAT_SUBTITLE_MAX_CHARS:
                return subtitle[: CHAT_SUBTITLE_MAX_CHARS - 1].rstrip() + "…"
            return subtitle
    return ""


def _default_supplementary_gids() -> str:
    gids = sorted({gid for gid in os.getgroups() if gid != os.getgid()})
    return ",".join(str(gid) for gid in gids)


def _normalize_csv(value: str | None) -> str:
    return core_shared.normalize_csv(value)


@dataclass(frozen=True)
class RuntimeIdentityEnvOverrides:
    uid_raw: str = ""
    gid_raw: str = ""
    supplementary_gids: str = ""
    shared_root: str = ""
    username: str = ""


def _runtime_identity_env_overrides() -> RuntimeIdentityEnvOverrides:
    return RuntimeIdentityEnvOverrides(
        uid_raw=str(os.environ.get(AGENT_HUB_HOST_UID_ENV, "")).strip(),
        gid_raw=str(os.environ.get(AGENT_HUB_HOST_GID_ENV, "")).strip(),
        supplementary_gids=_normalize_csv(str(os.environ.get(AGENT_HUB_HOST_SUPP_GIDS_ENV, ""))),
        shared_root=str(os.environ.get(AGENT_HUB_SHARED_ROOT_ENV, "")).strip(),
        username=str(os.environ.get(AGENT_HUB_HOST_USER_ENV, "")).strip(),
    )


def _resolve_hub_runtime_identity(
    runtime_config: AgentRuntimeConfig | None = None,
    env_overrides: RuntimeIdentityEnvOverrides | None = None,
) -> tuple[int, int, str]:
    identity_config = core_identity.parse_runtime_identity_config(runtime_config)
    host_supp_gids = env_overrides.supplementary_gids if env_overrides is not None else ""
    default_supplementary = _default_supplementary_gids() if not host_supp_gids else host_supp_gids
    if identity_config.uid_raw or identity_config.gid_raw:
        uid, gid = core_identity.parse_configured_uid_gid(
            identity_config,
            error_factory=lambda message: IdentityError(message),
        )
        resolved_supplementary = identity_config.supplementary_gids or default_supplementary
        assert uid is not None and gid is not None
        return uid, gid, resolved_supplementary

    host_uid_raw = env_overrides.uid_raw if env_overrides is not None else ""
    host_gid_raw = env_overrides.gid_raw if env_overrides is not None else ""
    if host_uid_raw or host_gid_raw:
        if not host_uid_raw or not host_gid_raw:
            raise IdentityError(
                f"{AGENT_HUB_HOST_UID_ENV} and {AGENT_HUB_HOST_GID_ENV} must be set together."
            )
        uid = core_identity.parse_non_negative_int_value(
            host_uid_raw,
            source_name=AGENT_HUB_HOST_UID_ENV,
            error_factory=lambda message: IdentityError(message),
        )
        gid = core_identity.parse_non_negative_int_value(
            host_gid_raw,
            source_name=AGENT_HUB_HOST_GID_ENV,
            error_factory=lambda message: IdentityError(message),
        )
        return uid, gid, host_supp_gids

    shared_root_raw = identity_config.shared_root or (env_overrides.shared_root if env_overrides is not None else "")
    if shared_root_raw:
        try:
            metadata = Path(shared_root_raw).stat()
        except OSError as exc:
            raise IdentityError(
                f"Failed to stat {AGENT_HUB_SHARED_ROOT_ENV}={shared_root_raw!r}: {exc}"
            ) from exc
        return int(metadata.st_uid), int(metadata.st_gid), host_supp_gids

    return os.getuid(), os.getgid(), default_supplementary


def _resolve_hub_effective_run_mode(runtime_config: AgentRuntimeConfig | None) -> tuple[str, str]:
    configured = DEFAULT_RUNTIME_RUN_MODE
    if runtime_config is not None:
        configured = str(runtime_config.runtime.run_mode or DEFAULT_RUNTIME_RUN_MODE).strip().lower()
    configured = configured or DEFAULT_RUNTIME_RUN_MODE
    effective = "docker" if configured == "auto" else configured
    return configured, effective


def _validate_hub_runtime_run_mode(runtime_config: AgentRuntimeConfig | None) -> None:
    if runtime_config is not None and not bool(runtime_config.runtime.strict_mode):
        raise ConfigError("Agent Hub requires runtime.strict_mode=true.")
    configured, effective = _resolve_hub_effective_run_mode(runtime_config)
    if effective == "docker":
        return
    raise ConfigError(
        "Agent Hub only supports effective docker runtime mode; "
        f"set runtime.run_mode to 'docker' or 'auto' (configured={configured!r}, effective={effective!r})."
    )


def _parse_gid_csv(value: str) -> list[int]:
    return core_shared.parse_gid_csv(
        value,
        strict=True,
        error_factory=lambda message: IdentityError(message),
    )


def _read_codex_auth(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return False, ""
    if not isinstance(payload, dict):
        return False, ""

    auth_mode = str(payload.get("auth_mode") or "").strip().lower()
    if auth_mode != "chatgpt":
        return False, auth_mode

    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return False, auth_mode

    refresh_token = str(tokens.get("refresh_token") or "").strip()
    return bool(refresh_token), auth_mode


def _snapshot_schema_version() -> int:
    # v8 invalidates snapshots that were built before and during the reverted
    # v7 window so project-in-image prepare flow uses deterministic writability
    # enforcement in all rebuilt snapshots.
    return 8


def _docker_remove_images(prefixes: tuple[str, ...], explicit_tags: set[str]) -> None:
    if shutil.which("docker") is None:
        return

    requested: set[str] = {tag.strip() for tag in explicit_tags if str(tag).strip()}
    list_result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        check=False,
        text=True,
        capture_output=True,
    )
    if list_result.returncode == 0:
        for raw in list_result.stdout.splitlines():
            tag = raw.strip()
            if not tag or tag == "<none>:<none>":
                continue
            if any(tag.startswith(prefix) for prefix in prefixes):
                requested.add(tag)

    if not requested:
        return

    subprocess.run(
        ["docker", "image", "rm", "-f", *sorted(requested)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _docker_remove_stale_containers(prefixes: tuple[str, ...]) -> int:
    normalized_prefixes = tuple(str(prefix or "").strip() for prefix in prefixes if str(prefix or "").strip())
    if not normalized_prefixes:
        return 0
    if shutil.which("docker") is None:
        return 0

    try:
        list_result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return 0
    if list_result.returncode != 0:
        return 0

    stale_names: set[str] = set()
    for raw_line in list_result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "\t" in line:
            name, state = line.split("\t", 1)
        else:
            name, state = line, ""
        normalized_name = str(name or "").strip()
        normalized_state = str(state or "").strip().lower()
        if not normalized_name:
            continue
        if not any(normalized_name.startswith(prefix) for prefix in normalized_prefixes):
            continue
        if normalized_state in {"running", "restarting", "paused"}:
            continue
        stale_names.add(normalized_name)

    if not stale_names:
        return 0

    try:
        subprocess.run(
            ["docker", "rm", "-f", *sorted(stale_names)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return 0
    return len(stale_names)


def _docker_fix_path_ownership(path: Path, uid: int, gid: int) -> None:
    if not path.exists():
        return
    if shutil.which("docker") is None:
        raise RuntimeError("docker command not found in PATH")
    if not _docker_image_exists(DEFAULT_AGENT_IMAGE):
        raise RuntimeError(
            f"Runtime image '{DEFAULT_AGENT_IMAGE}' is not available for ownership repair."
        )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "bash",
            "--volume",
            f"{path}:/target",
            DEFAULT_AGENT_IMAGE,
            "-lc",
            f"chown -R {uid}:{gid} /target",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        combined = f"{result.stdout or ''}{result.stderr or ''}".strip()
        detail = combined or f"docker run exited with code {result.returncode}"
        raise RuntimeError(f"Failed to repair path ownership for {path}: {detail}")


def _detect_default_branch(repo_url: str, env: dict[str, str] | None = None) -> str:
    result = _run(["git", "ls-remote", "--symref", repo_url, "HEAD"], capture=True, check=False, env=env)
    if result.returncode != 0:
        raise ConfigError(
            "Unable to determine repository default branch via remote HEAD. "
            f"repo_url={repo_url!r} exit_code={result.returncode}"
        )

    for line in result.stdout.splitlines():
        if not line.startswith("ref:"):
            continue
        parts = line.replace("\t", " ").split()
        if len(parts) < 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/heads/"):
            return ref.rsplit("/", 1)[-1]

    raise ConfigError(f"Unable to determine repository default branch from remote HEAD for {repo_url!r}.")


def _git_default_remote_branch(repo_dir: Path) -> str | None:
    result = _run_for_repo(["symbolic-ref", "refs/remotes/origin/HEAD"], repo_dir, capture=True, check=False)
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    if not ref.startswith("refs/remotes/origin/"):
        return None
    return ref.rsplit("/", 1)[-1]


def _git_has_remote_branch(repo_dir: Path, branch: str) -> bool:
    result = _run_for_repo(["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], repo_dir, check=False)
    return result.returncode == 0


def _is_process_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


def _stop_process(pid: int) -> None:
    if not _is_process_running(pid):
        return

    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, OSError):
        pgid = None

    try:
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return

    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if not _is_process_running(pid):
            return
        time.sleep(0.1)

    if _is_process_running(pid):
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                return


def _stop_processes(pids: list[int], timeout_seconds: float = 4.0) -> int:
    active = [pid for pid in sorted({int(pid) for pid in pids}) if _is_process_running(pid)]
    if not active:
        return 0

    groups: dict[int, int] = {}
    for pid in active:
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, OSError):
            pgid = 0
        groups[pid] = pgid
        try:
            if pgid:
                os.killpg(pgid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                continue

    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    alive = active
    while time.monotonic() < deadline:
        alive = [pid for pid in alive if _is_process_running(pid)]
        if not alive:
            return len(active)
        time.sleep(0.1)

    for pid in alive:
        pgid = groups.get(pid, 0)
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                continue

    return len(active)


def _signal_process_group_winch(pid: int) -> None:
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = 0

    if pgid:
        try:
            os.killpg(pgid, signal.SIGWINCH)
            return
        except OSError:
            pass

    try:
        os.kill(pid, signal.SIGWINCH)
    except OSError:
        pass


def _resolve_hub_runtime_username(
    uid: int,
    runtime_config: AgentRuntimeConfig | None = None,
    env_overrides: RuntimeIdentityEnvOverrides | None = None,
) -> str:
    if runtime_config is not None:
        configured_identity_user = core_identity.parse_runtime_identity_config(runtime_config).username
        if configured_identity_user:
            return configured_identity_user
    configured = env_overrides.username if env_overrides is not None else ""
    if configured:
        return configured
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError) as exc:
        raise IdentityError(
            "Host username resolution failed for runtime identity "
            f"(uid={uid}). Set {AGENT_HUB_HOST_USER_ENV}."
        ) from exc


from agent_hub.server_hubstate_ops_mixin import HubStateOpsMixin
from agent_hub.server_hubstate_runtime_mixin import HubStateRuntimeMixin


class HubState(HubStateRuntimeMixin, HubStateOpsMixin):
    def __init__(
        self,
        data_dir: Path,
        config_file: Path,
        runtime_config: AgentRuntimeConfig | None = None,
        runtime_identity_overrides: RuntimeIdentityEnvOverrides | None = None,
        system_prompt_file: Path | None = None,
        hub_host: str = DEFAULT_HOST,
        hub_port: int = DEFAULT_PORT,
        artifact_publish_base_url: str | None = None,
        ui_lifecycle_debug: bool = False,
        reconcile_project_build_on_init: bool = True,
    ):
        self.runtime_config = runtime_config
        if runtime_identity_overrides is not None:
            self.runtime_identity_overrides = runtime_identity_overrides
        elif self.runtime_config is None:
            self.runtime_identity_overrides = _runtime_identity_env_overrides()
        else:
            self.runtime_identity_overrides = RuntimeIdentityEnvOverrides()
        _validate_hub_runtime_run_mode(self.runtime_config)
        self.local_uid, self.local_gid, self.local_supp_gids = _resolve_hub_runtime_identity(
            self.runtime_config,
            self.runtime_identity_overrides,
        )
        self.local_user = _resolve_hub_runtime_username(
            self.local_uid,
            self.runtime_config,
            self.runtime_identity_overrides,
        )
        self.local_umask = "0022"
        self.runtime_identity = core_identity.RuntimeIdentity(
            username=self.local_user,
            uid=int(self.local_uid),
            gid=int(self.local_gid),
            supplementary_gids=self.local_supp_gids,
            umask=self.local_umask,
        )
        self.settings_service = SettingsService(
            default_agent_type=DEFAULT_CHAT_AGENT_TYPE,
            default_chat_layout_engine=DEFAULT_CHAT_LAYOUT_ENGINE,
            normalize_chat_agent_type=_normalize_chat_agent_type,
            normalize_chat_layout_engine=_normalize_chat_layout_engine,
        )
        self.data_dir = Path(data_dir).resolve()
        self.host_agent_home = (self.data_dir / "agent-home" / self.local_user).resolve()
        self.host_codex_dir = self.host_agent_home / ".codex"
        self.agent_tools_mcp_runtime_script = (
            self.host_codex_dir / AGENT_TOOLS_MCP_RUNTIME_DIR_NAME / AGENT_TOOLS_MCP_RUNTIME_FILE_NAME
        )
        self.openai_codex_auth_file = self.host_codex_dir / OPENAI_CODEX_AUTH_FILE_NAME

        self.config_file = config_file
        self.system_prompt_file = Path(system_prompt_file or _default_system_prompt_file())
        self.hub_host = str(hub_host or DEFAULT_HOST)
        self.hub_port = int(hub_port or DEFAULT_PORT)
        self.artifact_publish_base_url = _resolve_artifact_publish_base_url(
            artifact_publish_base_url,
            self.hub_port,
        )
        self.auth_domain = AuthDomain(state=self)
        self.auto_config_domain = AutoConfigDomain(state=self)
        self.chat_runtime_domain = ChatRuntimeDomain(state=self)
        self.credentials_domain = CredentialsDomain(state=self)
        self.project_domain = ProjectDomain(state=self)
        self.runtime_domain = RuntimeDomain(
            runtime_factory=ChatRuntime,
            is_process_running=lambda pid: _is_process_running(pid),
            signal_process_group_winch=lambda pid: _signal_process_group_winch(pid),
            chat_log_path=self.chat_log,
            on_runtime_exit=lambda chat_id, exit_code: self._record_chat_runtime_exit(
                chat_id,
                exit_code,
                reason="chat_runtime_reader_completed",
            ),
            collect_submitted_prompts=self._collect_submitted_prompts_from_input,
            record_submitted_prompt=self._record_submitted_prompt,
            terminal_queue_max=TERMINAL_QUEUE_MAX,
            default_cols=DEFAULT_PTY_COLS,
            default_rows=DEFAULT_PTY_ROWS,
        )
        # Back-compat aliases for existing tests and transitional callers.
        self._runtime_lock = self.runtime_domain._runtime_lock
        self._chat_runtimes = self.runtime_domain._chat_runtimes
        self.auth_service = AuthService(
            domain=self.auth_domain,
            default_artifact_publish_host=DEFAULT_ARTIFACT_PUBLISH_HOST,
            callback_forward_timeout_seconds=OPENAI_ACCOUNT_CALLBACK_FORWARD_TIMEOUT_SECONDS,
        )
        self.project_service = ProjectService(domain=self.project_domain)
        self.chat_service = ChatService(domain=self.chat_runtime_domain)
        self.runtime_service = RuntimeService(state=self)
        self.credentials_service = CredentialsService(
            domain=self.credentials_domain,
            agent_tools_token_header=AGENT_TOOLS_TOKEN_HEADER,
        )
        self.artifacts_service = ArtifactsService(
            state=self,
            agent_tools_token_header=AGENT_TOOLS_TOKEN_HEADER,
            artifact_token_header="x-agent-hub-artifact-token",
        )
        self.auto_config_service = AutoConfigService(domain=self.auto_config_domain)
        self.app_state_service = AppStateService(state=self)
        self.event_service = EventService(state=self)
        self.lifecycle_service = LifecycleService(state=self)
        self._lock = Lock()
        self._events_lock = Lock()
        self._project_build_lock = Lock()
        self._project_build_threads: dict[str, Thread] = {}
        self._event_listeners: set[queue.Queue[dict[str, Any] | None]] = set()
        self._openai_login_lock = Lock()
        self._openai_login_session: OpenAIAccountLoginSession | None = None
        self._chat_input_lock = Lock()
        self._chat_input_buffers: dict[str, str] = {}
        self._chat_input_ansi_carry: dict[str, str] = {}
        self._chat_title_job_lock = Lock()
        self._chat_title_jobs_inflight: set[str] = set()
        self._chat_title_jobs_pending: set[str] = set()
        self._github_token_lock = Lock()
        self._github_token_cache: dict[str, Any] = {}
        self._github_setup_lock = Lock()
        self._github_setup_session: GithubAppSetupSession | None = None
        self._agent_capabilities_lock = Lock()
        self._agent_capabilities = _default_agent_capabilities_cache_payload()
        self._agent_capabilities_discovery_thread: Thread | None = None
        self._startup_reconcile_lock = Lock()
        self._startup_reconcile_thread: Thread | None = None
        self._startup_reconcile_scheduled = False
        self._agent_tools_sessions_lock = Lock()
        self._agent_tools_sessions: dict[str, dict[str, Any]] = {}
        self._auto_config_requests_lock = Lock()
        self._auto_config_requests: dict[str, AutoConfigRequestState] = {}
        self._project_build_requests_lock = Lock()
        self._project_build_requests: dict[str, ProjectBuildRequestState] = {}
        self.ui_lifecycle_debug = bool(ui_lifecycle_debug)
        self.state_file = self.data_dir / STATE_FILE_NAME
        self._state_store = HubStateStore(
            state_file=self.state_file,
            lock=self._lock,
            new_state_factory=_new_state,
        )
        self.agent_capabilities_cache_file = self.data_dir / AGENT_CAPABILITIES_CACHE_FILE_NAME
        self.project_dir = self.data_dir / "projects"
        self.chat_dir = self.data_dir / "chats"
        self.log_dir = self.data_dir / "logs"
        self.runtime_tmp_dir = self.data_dir / RUNTIME_TMP_ROOT_DIR_NAME
        self.runtime_project_tmp_dir = self.runtime_tmp_dir / RUNTIME_TMP_PROJECTS_DIR_NAME
        self.artifacts_dir = self.data_dir / ARTIFACT_STORAGE_DIR_NAME
        self.chat_artifacts_dir = self.artifacts_dir / ARTIFACT_STORAGE_CHAT_DIR_NAME
        self.session_artifacts_dir = self.artifacts_dir / ARTIFACT_STORAGE_SESSION_DIR_NAME
        self.secrets_dir = self.data_dir / SECRETS_DIR_NAME
        self.chat_runtime_configs_dir = self.data_dir / CHAT_RUNTIME_CONFIGS_DIR_NAME
        self.openai_credentials_file = self.secrets_dir / OPENAI_CREDENTIALS_FILE_NAME
        self.github_app_settings_file = self.secrets_dir / GITHUB_APP_SETTINGS_FILE_NAME
        self.github_app_installation_file = self.secrets_dir / GITHUB_APP_INSTALLATION_FILE_NAME
        self.github_tokens_file = self.secrets_dir / GITHUB_TOKENS_FILE_NAME
        self.gitlab_tokens_file = self.secrets_dir / GITLAB_TOKENS_FILE_NAME
        self.git_credentials_dir = self.secrets_dir / GIT_CREDENTIALS_DIR_NAME
        self.github_app_settings: GithubAppSettings | None = None
        self.github_app_settings_error = ""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_tmp_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_project_tmp_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.chat_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.session_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.chat_runtime_configs_dir.mkdir(parents=True, exist_ok=True)
        self.git_credentials_dir.mkdir(parents=True, exist_ok=True)
        self.host_codex_dir.mkdir(parents=True, exist_ok=True)
        self._reload_github_app_settings()
        self._load_agent_capabilities_cache()
        if reconcile_project_build_on_init:
            self._reconcile_project_build_state()



@click.command(help="Run the local agent hub.")
@click.option("--data-dir", default=str(_default_data_dir()), show_default=True, type=click.Path(file_okay=False, path_type=Path), help="Directory for hub state and chat workspaces.")
@click.option("--config-file", default=str(_default_config_file()), show_default=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Agent config file to pass into every chat.")
@click.option(
    "--system-prompt-file",
    default=str(_default_system_prompt_file()),
    show_default=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Core system prompt markdown file to apply across all chat agents.",
)
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int)
@click.option(
    "--artifact-publish-base-url",
    default="",
    show_default=f"auto (http://{DEFAULT_ARTIFACT_PUBLISH_HOST}:<port>)",
    help="Base URL reachable from agent_cli containers for artifact publish requests.",
)
@click.option("--frontend-build/--no-frontend-build", default=True, show_default=True, help="Automatically build the React frontend before starting the server.")
@click.option("--clean-start", is_flag=True, default=False, help="Clear hub chat artifacts and cached setup images before serving.")
@click.option(
    "--log-level",
    default=None,
    show_default="config logging.level or info",
    type=click.Choice(HUB_LOG_LEVEL_CHOICES, case_sensitive=False),
    help="Hub logging verbosity (applies to Agent Hub logs and Uvicorn).",
)
@click.option(
    "--ui-lifecycle-debug/--no-ui-lifecycle-debug",
    default=False,
    show_default=True,
    help="Enable verbose frontend lifecycle and redraw logging in the browser console.",
)
@click.option("--reload", is_flag=True, default=False)
def main(
    data_dir: Path,
    config_file: Path,
    system_prompt_file: Path,
    host: str,
    port: int,
    artifact_publish_base_url: str,
    frontend_build: bool,
    clean_start: bool,
    log_level: str | None,
    ui_lifecycle_debug: bool,
    reload: bool,
) -> None:
    if _default_config_file() and not Path(config_file).exists():
        raise click.ClickException(f"Missing config file: {config_file}")
    if _default_system_prompt_file() and not Path(system_prompt_file).exists():
        raise click.ClickException(f"Missing system prompt file: {system_prompt_file}")
    try:
        runtime_config = load_agent_runtime_config(config_file)
    except ConfigError as exc:
        click.echo(
            json.dumps(
                {
                    "event": "agent_hub_config_load_error",
                    "config_path": str(config_file),
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "event": "agent_hub_config_loaded",
                "config_path": str(config_file),
                "run_mode": str(runtime_config.runtime.run_mode or ""),
                "strict_mode": bool(runtime_config.runtime.strict_mode),
            },
            sort_keys=True,
        ),
        err=True,
    )
    try:
        _validate_hub_runtime_run_mode(runtime_config)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    normalized_log_level = _resolve_hub_log_level(log_level, runtime_config)
    _configure_hub_logging(normalized_log_level)
    _configure_domain_log_levels(runtime_config)
    LOGGER.info(
        "Starting Agent Hub host=%s port=%s log_level=%s reload=%s",
        host,
        port,
        normalized_log_level,
        reload,
        extra={
            "component": "startup",
            "operation": "hub_start",
            "result": "started",
            "request_id": "",
            "project_id": "",
            "chat_id": "",
            "duration_ms": 0,
            "error_class": "",
        },
    )
    if frontend_build:
        _ensure_frontend_built(data_dir)

    try:
        state = HubState(
            data_dir=data_dir,
            config_file=config_file,
            runtime_config=runtime_config,
            system_prompt_file=system_prompt_file,
            hub_host=host,
            hub_port=port,
            artifact_publish_base_url=artifact_publish_base_url,
            ui_lifecycle_debug=ui_lifecycle_debug,
        )
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    LOGGER.info(
        "Artifact publish base URL: %s",
        state.artifact_publish_base_url,
        extra={
            "component": "startup",
            "operation": "artifact_publish_base_url",
            "result": "resolved",
            "request_id": "",
            "project_id": "",
            "chat_id": "",
            "duration_ms": 0,
            "error_class": "",
        },
    )
    if clean_start:
        summary = state.clean_start()
        click.echo(
            "Clean start completed: "
            f"stopped_chats={summary['stopped_chats']} "
            f"cleared_chats={summary['cleared_chats']} "
            f"projects_reset={summary['projects_reset']} "
            f"docker_images_requested={summary['docker_images_requested']}"
        )
    state.schedule_startup_reconcile()

    app = FastAPI()
    app.state.hub_state = state

    @app.exception_handler(TypedAgentError)
    async def _handle_typed_agent_error(_request: Request, exc: TypedAgentError) -> JSONResponse:
        status, payload = _core_error_payload(exc)
        return JSONResponse(status_code=status, content=payload)

    @app.exception_handler(HTTPException)
    async def _handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=int(exc.status_code or 500),
            content={"error_code": _http_error_code(int(exc.status_code or 500)), "detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    frontend_dist = _frontend_dist_dir()
    frontend_index = _frontend_index_file()

    register_hub_routes(
        app,
        state=state,
        frontend_dist=frontend_dist,
        frontend_index=frontend_index,
        logger=LOGGER,
        event_type_snapshot=EVENT_TYPE_SNAPSHOT,
        agent_type_codex=AGENT_TYPE_CODEX,
        iso_now=_iso_now,
        frontend_not_built_page=_frontend_not_built_page,
        coerce_bool=_coerce_bool,
        github_app_setup_callback_page=_github_app_setup_callback_page,
        normalize_openai_account_login_method=_normalize_openai_account_login_method,
        openai_callback_request_context_from_request=_openai_callback_request_context_from_request,
        normalize_chat_agent_type=_normalize_chat_agent_type,
        normalize_base_image_mode=_normalize_base_image_mode,
        normalize_project_credential_binding=_normalize_project_credential_binding,
        parse_mounts=_parse_mounts,
        empty_list=_empty_list,
        parse_env_vars=_parse_env_vars,
        compact_whitespace=_compact_whitespace,
        parse_artifact_request_payload=_parse_artifact_request_payload,
        cleanup_uploaded_artifact_paths=_cleanup_uploaded_artifact_paths,
    )

    uvicorn.run(app, host=host, port=port, reload=reload, log_level=_uvicorn_log_level(normalized_log_level))


if __name__ == "__main__":
    main()
