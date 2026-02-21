import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";

const POLL_MS = 4000;

function emptyVolume() {
  return { host: "", container: "", mode: "rw" };
}

function emptyEnvVar() {
  return { key: "", value: "" };
}

function emptyCreateForm() {
  return {
    repoUrl: "",
    name: "",
    defaultBranch: "",
    baseImageMode: "tag",
    baseImageValue: "",
    setupScript: "",
    defaultVolumes: [],
    defaultEnvVars: []
  };
}

function normalizeBaseMode(mode) {
  return mode === "repo_path" ? "repo_path" : "tag";
}

function baseModeLabel(mode) {
  return mode === "repo_path" ? "Repo path" : "Docker tag";
}

function baseInputPlaceholder(mode) {
  if (mode === "repo_path") {
    return "Path in repo to Dockerfile or dir (e.g. docker/base or docker/base/Dockerfile)";
  }
  return "Docker image tag (e.g. nvcr.io/nvidia/isaac-lab:2.3.2)";
}

function parseMountEntry(spec, mode) {
  if (typeof spec !== "string") {
    return null;
  }
  const idx = spec.indexOf(":");
  if (idx <= 0 || idx === spec.length - 1) {
    return null;
  }
  return {
    host: spec.slice(0, idx),
    container: spec.slice(idx + 1),
    mode: mode === "ro" ? "ro" : "rw"
  };
}

function mountRowsFromArrays(roMounts, rwMounts) {
  const rows = [];
  for (const spec of roMounts || []) {
    const parsed = parseMountEntry(spec, "ro");
    if (parsed) {
      rows.push(parsed);
    }
  }
  for (const spec of rwMounts || []) {
    const parsed = parseMountEntry(spec, "rw");
    if (parsed) {
      rows.push(parsed);
    }
  }
  return rows;
}

function envRowsFromArray(entries) {
  const rows = [];
  for (const entry of entries || []) {
    const idx = entry.indexOf("=");
    if (idx < 0) {
      rows.push({ key: entry, value: "" });
      continue;
    }
    rows.push({ key: entry.slice(0, idx), value: entry.slice(idx + 1) });
  }
  return rows;
}

function buildMountPayload(rows) {
  const roMounts = [];
  const rwMounts = [];
  for (const row of rows || []) {
    const host = String(row.host || "").trim();
    const container = String(row.container || "").trim();
    const mode = row.mode === "ro" ? "ro" : "rw";
    if (!host && !container) {
      continue;
    }
    if (!host || !container) {
      throw new Error("Each volume needs both local path and container path.");
    }
    const entry = `${host}:${container}`;
    if (mode === "ro") {
      roMounts.push(entry);
    } else {
      rwMounts.push(entry);
    }
  }
  return { roMounts, rwMounts };
}

function buildEnvPayload(rows) {
  const envVars = [];
  for (const row of rows || []) {
    const key = String(row.key || "").trim();
    const value = String(row.value || "");
    if (!key && !value) {
      continue;
    }
    if (!key) {
      throw new Error("Environment variable key is required.");
    }
    envVars.push(`${key}=${value}`);
  }
  return envVars;
}

function setupCommandCount(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean).length;
}

function projectStatusInfo(buildStatus) {
  if (buildStatus === "ready") {
    return { key: "ready", label: "Ready" };
  }
  if (buildStatus === "building") {
    return { key: "building", label: "Building image" };
  }
  if (buildStatus === "failed") {
    return { key: "failed", label: "Build failed" };
  }
  return { key: "pending", label: "Needs build" };
}

function SpinnerLabel({ text }) {
  return (
    <>
      <span className="inline-spinner" aria-hidden="true" />
      <span>{text}</span>
    </>
  );
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

async function fetchText(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.text();
}

function terminalSocketUrl(chatId) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/api/chats/${chatId}/terminal`;
}

function ChatTerminal({ chatId, running }) {
  const shellRef = useRef(null);
  const hostRef = useRef(null);
  const [status, setStatus] = useState(running ? "connecting" : "offline");

  useEffect(() => {
    if (!running) {
      setStatus("offline");
      return undefined;
    }
    if (!hostRef.current) {
      return undefined;
    }

    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
      fontSize: 13,
      scrollback: 5000,
      theme: {
        background: "#0b1018",
        foreground: "#e7edf7",
        cursor: "#10a37f"
      }
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(hostRef.current);
    fitAddon.fit();
    terminal.focus();

    const ws = new WebSocket(terminalSocketUrl(chatId));
    setStatus("connecting");

    const sendResize = () => {
      if (ws.readyState !== WebSocket.OPEN) {
        return;
      }
      const cols = Math.max(1, terminal.cols || 1);
      const rows = Math.max(1, terminal.rows || 1);
      ws.send(JSON.stringify({ type: "resize", cols, rows }));
    };

    const inputDisposable = terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data }));
      }
    });

    const onOpen = () => {
      setStatus("connected");
      fitAddon.fit();
      sendResize();
      terminal.focus();
    };
    const onMessage = (event) => {
      if (typeof event.data === "string") {
        terminal.write(event.data);
      }
    };
    const onClose = () => {
      setStatus("closed");
    };
    const onError = () => {
      setStatus("error");
    };
    const onResize = () => {
      fitAddon.fit();
      sendResize();
    };

    let resizeObserver;
    if (typeof ResizeObserver !== "undefined" && shellRef.current) {
      resizeObserver = new ResizeObserver(() => {
        fitAddon.fit();
        sendResize();
      });
      resizeObserver.observe(shellRef.current);
    }

    ws.addEventListener("open", onOpen);
    ws.addEventListener("message", onMessage);
    ws.addEventListener("close", onClose);
    ws.addEventListener("error", onError);
    window.addEventListener("resize", onResize);

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      window.removeEventListener("resize", onResize);
      ws.removeEventListener("open", onOpen);
      ws.removeEventListener("message", onMessage);
      ws.removeEventListener("close", onClose);
      ws.removeEventListener("error", onError);
      inputDisposable.dispose();
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
      terminal.dispose();
    };
  }, [chatId, running]);

  return (
    <div className="terminal-shell chat-terminal-shell" ref={shellRef}>
      <div className="terminal-toolbar">
        <span className={`terminal-badge ${status}`}>{status}</span>
      </div>
      <div className="terminal-view" ref={hostRef} />
    </div>
  );
}

function ProjectBuildTerminal({ text }) {
  const hostRef = useRef(null);
  const terminalRef = useRef(null);
  const fitRef = useRef(null);

  useEffect(() => {
    if (!hostRef.current) {
      return undefined;
    }

    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: false,
      disableStdin: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
      fontSize: 12,
      scrollback: 10000,
      theme: {
        background: "#0b1018",
        foreground: "#e7edf7"
      }
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(hostRef.current);
    fitAddon.fit();
    terminalRef.current = terminal;
    fitRef.current = fitAddon;

    const onResize = () => fitAddon.fit();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      terminalRef.current = null;
      fitRef.current = null;
      terminal.dispose();
    };
  }, []);

  useEffect(() => {
    const terminal = terminalRef.current;
    if (!terminal) {
      return;
    }
    terminal.reset();
    terminal.write(text || "Preparing project image...\r\n");
    terminal.scrollToBottom();
    fitRef.current?.fit();
  }, [text]);

  return (
    <div className="terminal-shell project-build-shell">
      <div className="terminal-toolbar">
        <span className="terminal-title">Image build output</span>
      </div>
      <div className="terminal-view project-build-view" ref={hostRef} />
    </div>
  );
}

function VolumeEditor({ rows, onChange }) {
  function updateRow(index, patch) {
    const next = [...rows];
    next[index] = { ...next[index], ...patch };
    onChange(next);
  }

  function removeRow(index) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function addRow() {
    onChange([...rows, emptyVolume()]);
  }

  return (
    <div className="widget-block">
      {rows.map((row, index) => (
        <div className="widget-row volume" key={`volume-${index}`}>
          <input
            value={row.host}
            onChange={(event) => updateRow(index, { host: event.target.value })}
            placeholder="Local path (e.g. /data/datasets)"
          />
          <input
            value={row.container}
            onChange={(event) => updateRow(index, { container: event.target.value })}
            placeholder="Container path (e.g. /workspace/data)"
          />
          <select value={row.mode} onChange={(event) => updateRow(index, { mode: event.target.value })}>
            <option value="rw">Read-write</option>
            <option value="ro">Read-only</option>
          </select>
          <button type="button" className="btn-secondary btn-small" onClick={() => removeRow(index)}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="btn-secondary btn-small" onClick={addRow}>
        Add volume
      </button>
    </div>
  );
}

function EnvVarEditor({ rows, onChange }) {
  function updateRow(index, patch) {
    const next = [...rows];
    next[index] = { ...next[index], ...patch };
    onChange(next);
  }

  function removeRow(index) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function addRow() {
    onChange([...rows, emptyEnvVar()]);
  }

  return (
    <div className="widget-block">
      {rows.map((row, index) => (
        <div className="widget-row env" key={`env-${index}`}>
          <input
            value={row.key}
            onChange={(event) => updateRow(index, { key: event.target.value })}
            placeholder="KEY"
          />
          <input
            value={row.value}
            onChange={(event) => updateRow(index, { value: event.target.value })}
            placeholder="VALUE"
          />
          <button type="button" className="btn-secondary btn-small" onClick={() => removeRow(index)}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="btn-secondary btn-small" onClick={addRow}>
        Add environment variable
      </button>
    </div>
  );
}

function projectDraftFromProject(project) {
  return {
    baseImageMode: normalizeBaseMode(project.base_image_mode),
    baseImageValue: String(project.base_image_value || ""),
    setupScript: String(project.setup_script || ""),
    defaultVolumes: mountRowsFromArrays(project.default_ro_mounts || [], project.default_rw_mounts || []),
    defaultEnvVars: envRowsFromArray(project.default_env_vars || [])
  };
}

function normalizeOpenAiProviderStatus(rawProvider) {
  return {
    provider: "openai",
    connected: Boolean(rawProvider?.connected),
    keyHint: String(rawProvider?.key_hint || ""),
    updatedAt: String(rawProvider?.updated_at || ""),
    accountConnected: Boolean(rawProvider?.account_connected),
    accountAuthMode: String(rawProvider?.account_auth_mode || ""),
    accountUpdatedAt: String(rawProvider?.account_updated_at || "")
  };
}

function normalizeOpenAiAccountSession(rawSession) {
  if (!rawSession || typeof rawSession !== "object") {
    return null;
  }
  return {
    id: String(rawSession.id || ""),
    method: String(rawSession.method || "browser_callback"),
    status: String(rawSession.status || ""),
    startedAt: String(rawSession.started_at || ""),
    completedAt: String(rawSession.completed_at || ""),
    exitCode: rawSession.exit_code == null ? null : Number(rawSession.exit_code),
    error: String(rawSession.error || ""),
    running: Boolean(rawSession.running),
    loginUrl: String(rawSession.login_url || ""),
    deviceCode: String(rawSession.device_code || ""),
    localCallbackUrl: String(rawSession.local_callback_url || ""),
    callbackPort: Number(rawSession.callback_port || 0) || 0,
    callbackPath: String(rawSession.callback_path || "/auth/callback"),
    logTail: String(rawSession.log_tail || "")
  };
}

function buildProxiedOpenAiLoginUrl(loginUrl) {
  const raw = String(loginUrl || "").trim();
  if (!raw) {
    return "";
  }
  try {
    const parsed = new URL(raw);
    if (!parsed.searchParams.has("redirect_uri")) {
      return raw;
    }
    parsed.searchParams.set("redirect_uri", `${window.location.origin}/openai-auth/callback`);
    return parsed.toString();
  } catch {
    return raw;
  }
}

function extractCallbackQuery(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.startsWith("?")) {
    return raw.slice(1);
  }
  if (raw.startsWith("http://") || raw.startsWith("https://")) {
    try {
      const parsed = new URL(raw);
      return parsed.search ? parsed.search.slice(1) : "";
    } catch {
      return "";
    }
  }
  if (raw.includes("?")) {
    return raw.split("?", 2)[1] || "";
  }
  return raw;
}

function formatTimestamp(isoText) {
  const normalized = String(isoText || "").trim();
  if (!normalized) {
    return "Never";
  }
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return normalized;
  }
  return parsed.toLocaleString();
}

function OpenAiAuthCallbackPage() {
  const [status, setStatus] = useState("forwarding");
  const [message, setMessage] = useState("Forwarding callback to the OpenAI login container...");

  useEffect(() => {
    let cancelled = false;
    async function forwardCallback() {
      const search = window.location.search || "";
      if (!search || search === "?") {
        if (!cancelled) {
          setStatus("error");
          setMessage("Missing callback query parameters.");
        }
        return;
      }

      try {
        const payload = await fetchJson(`/api/settings/auth/openai/account/callback${search}`);
        if (cancelled) {
          return;
        }
        const forwarded = payload?.callback;
        if (forwarded?.forwarded) {
          setStatus("complete");
          setMessage(
            forwarded?.response_summary
              ? `Callback forwarded. ${forwarded.response_summary}`
              : "Callback forwarded. Return to Agent Hub and wait for login status to become connected."
          );
        } else {
          setStatus("error");
          setMessage("Callback forwarding did not complete.");
        }
      } catch (err) {
        if (!cancelled) {
          setStatus("error");
          setMessage(err.message || String(err));
        }
      }
    }

    forwardCallback();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="callback-page">
      <section className="panel callback-panel">
        <h2>OpenAI Account Login</h2>
        <p className={`meta callback-status ${status}`}>{message}</p>
        <div className="actions">
          <button type="button" className="btn-primary" onClick={() => window.location.assign("/")}>
            Return to Agent Hub
          </button>
        </div>
      </section>
    </main>
  );
}

function HubApp() {
  const [hubState, setHubState] = useState({ projects: [], chats: [] });
  const [error, setError] = useState("");
  const [createForm, setCreateForm] = useState(() => emptyCreateForm());
  const [projectDrafts, setProjectDrafts] = useState({});
  const [editingProjects, setEditingProjects] = useState({});
  const [projectBuildLogs, setProjectBuildLogs] = useState({});
  const [projectStaticLogs, setProjectStaticLogs] = useState({});
  const [openBuildLogs, setOpenBuildLogs] = useState({});
  const [activeTerminalChatId, setActiveTerminalChatId] = useState("");
  const [activeTab, setActiveTab] = useState("projects");
  const [collapsedChats, setCollapsedChats] = useState({});
  const [pendingSessions, setPendingSessions] = useState([]);
  const [pendingProjectBuilds, setPendingProjectBuilds] = useState({});
  const [pendingChatStarts, setPendingChatStarts] = useState({});
  const [openAiProviderStatus, setOpenAiProviderStatus] = useState(() =>
    normalizeOpenAiProviderStatus(null)
  );
  const [openAiAuthLoaded, setOpenAiAuthLoaded] = useState(false);
  const [openAiCardExpanded, setOpenAiCardExpanded] = useState(false);
  const [openAiCardExpansionInitialized, setOpenAiCardExpansionInitialized] = useState(false);
  const [openAiDraftKey, setOpenAiDraftKey] = useState("");
  const [verifyOpenAiOnSave, setVerifyOpenAiOnSave] = useState(true);
  const [showOpenAiDraftKey, setShowOpenAiDraftKey] = useState(false);
  const [openAiSaving, setOpenAiSaving] = useState(false);
  const [openAiDisconnecting, setOpenAiDisconnecting] = useState(false);
  const [openAiAccountSession, setOpenAiAccountSession] = useState(null);
  const [openAiAccountStarting, setOpenAiAccountStarting] = useState(false);
  const [openAiAccountCancelling, setOpenAiAccountCancelling] = useState(false);
  const [openAiAccountDisconnecting, setOpenAiAccountDisconnecting] = useState(false);
  const [openAiAccountCallbackInput, setOpenAiAccountCallbackInput] = useState("");

  const refreshState = useCallback(async () => {
    const payload = await fetchJson("/api/state");
    setHubState(payload);
    const serverChatMap = new Map((payload.chats || []).map((chat) => [chat.id, chat]));
    setPendingSessions((prev) =>
      prev.flatMap((session) => {
        if (!session.server_chat_id) {
          return [session];
        }
        const onServer = serverChatMap.has(session.server_chat_id);
        const seenOnServer = Boolean(session.seen_on_server || onServer);
        if (seenOnServer && !onServer) {
          return [];
        }
        if (seenOnServer === Boolean(session.seen_on_server)) {
          return [session];
        }
        return [{ ...session, seen_on_server: seenOnServer }];
      })
    );
    setPendingChatStarts((prev) => {
      const next = {};
      for (const [chatId, pending] of Object.entries(prev)) {
        if (!pending) {
          continue;
        }
        const serverChat = serverChatMap.get(chatId);
        if (serverChat && !serverChat.is_running) {
          next[chatId] = true;
        }
      }
      return next;
    });
    setPendingProjectBuilds((prev) => {
      const next = {};
      for (const project of payload.projects || []) {
        if (prev[project.id] && String(project.build_status || "") === "building") {
          next[project.id] = true;
        }
      }
      return next;
    });
  }, []);

  const refreshAuthSettings = useCallback(async () => {
    const [authPayload, sessionPayload] = await Promise.all([
      fetchJson("/api/settings/auth"),
      fetchJson("/api/settings/auth/openai/account/session")
    ]);
    const provider = authPayload?.providers?.openai;
    setOpenAiProviderStatus(normalizeOpenAiProviderStatus(provider));
    setOpenAiAccountSession(normalizeOpenAiAccountSession(sessionPayload?.session));
    setOpenAiAuthLoaded(true);
  }, []);

  const visibleChats = useMemo(() => {
    const serverChats = hubState.chats || [];
    const serverChatById = new Map(serverChats.map((chat) => [chat.id, chat]));
    const mappedServerIds = new Set();
    const merged = [];

    for (const session of pendingSessions) {
      const serverId = String(session.server_chat_id || "");
      if (serverId && serverChatById.has(serverId)) {
        mappedServerIds.add(serverId);
        const serverChat = serverChatById.get(serverId);
        merged.push({ ...serverChat, id: session.ui_id, server_chat_id: serverId });
        continue;
      }
      const knownServerIds = new Set(session.known_server_chat_ids || []);
      const matchedServerChat = serverChats.find(
        (chat) =>
          !mappedServerIds.has(chat.id) &&
          String(chat.project_id || "") === String(session.project_id || "") &&
          !knownServerIds.has(chat.id)
      );
      if (matchedServerChat) {
        mappedServerIds.add(matchedServerChat.id);
        merged.push({
          ...matchedServerChat,
          id: session.ui_id,
          server_chat_id: matchedServerChat.id,
          is_pending_start: true
        });
        continue;
      }
      merged.push({
        id: session.ui_id,
        server_chat_id: serverId,
        name: "new-chat",
        display_name: "New chat",
        display_subtitle: "Creating workspace and starting worker…",
        status: "starting",
        is_running: false,
        is_pending_start: true,
        project_id: session.project_id,
        project_name: session.project_name || "Unknown",
        workspace: "",
        container_workspace: "",
        ro_mounts: [],
        rw_mounts: [],
        env_vars: []
      });
    }

    for (const chat of serverChats) {
      if (!mappedServerIds.has(chat.id)) {
        merged.push(chat);
      }
    }

    return merged;
  }, [hubState.chats, pendingSessions]);

  useEffect(() => {
    let mounted = true;

    async function refreshAndHandleError() {
      try {
        await Promise.all([refreshState(), refreshAuthSettings()]);
        if (mounted) {
          setError("");
        }
      } catch (err) {
        if (mounted) {
          setError(err.message || String(err));
        }
      }
    }

    refreshAndHandleError();
    const interval = setInterval(refreshAndHandleError, POLL_MS);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [refreshState, refreshAuthSettings]);

  useEffect(() => {
    setProjectDrafts((prev) => {
      const next = {};
      for (const project of hubState.projects) {
        next[project.id] = prev[project.id] || projectDraftFromProject(project);
      }
      return next;
    });
  }, [hubState.projects]);

  useEffect(() => {
    setEditingProjects((prev) => {
      const next = {};
      for (const project of hubState.projects) {
        next[project.id] = Boolean(prev[project.id]);
      }
      return next;
    });
  }, [hubState.projects]);

  useEffect(() => {
    setActiveTerminalChatId((current) => {
      if (!current) {
        return current;
      }
      const selected = visibleChats.find((chat) => chat.id === current);
      if (!selected) {
        return "";
      }
      const resolvedChatId = String(selected.server_chat_id || selected.id);
      const isRunning = Boolean(selected.is_running);
      const isStarting = Boolean(
        pendingChatStarts[resolvedChatId] || selected.is_pending_start || String(selected.status || "") === "starting"
      );
      if (!isRunning && !isStarting) {
        return "";
      }
      return current;
    });
  }, [visibleChats, pendingChatStarts]);

  useEffect(() => {
    setCollapsedChats((prev) => {
      const next = {};
      for (const chat of visibleChats) {
        next[chat.id] = prev[chat.id] ?? true;
      }
      return next;
    });
  }, [visibleChats]);

  useEffect(() => {
    let stopped = false;
    const activeProjects = hubState.projects.filter((project) => {
      const status = String(project.build_status || "");
      return status === "building";
    });

    if (activeProjects.length === 0) {
      setProjectBuildLogs({});
      return undefined;
    }

    async function refreshProjectLogs() {
      const updates = {};
      await Promise.all(
        activeProjects.map(async (project) => {
          try {
            updates[project.id] = await fetchText(`/api/projects/${project.id}/build-logs`);
          } catch {
            updates[project.id] = "";
          }
        })
      );
      if (!stopped) {
        setProjectBuildLogs((prev) => {
          const next = {};
          for (const project of activeProjects) {
            if (prev[project.id] !== undefined) {
              next[project.id] = prev[project.id];
            }
          }
          return { ...next, ...updates };
        });
      }
    }

    refreshProjectLogs();
    const interval = setInterval(refreshProjectLogs, 1500);
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [hubState.projects]);

  useEffect(() => {
    if (!openAiAccountSession?.running) {
      return undefined;
    }
    let cancelled = false;

    async function refreshAccountSession() {
      try {
        const payload = await fetchJson("/api/settings/auth/openai/account/session");
        if (cancelled) {
          return;
        }
        setOpenAiAccountSession(normalizeOpenAiAccountSession(payload?.session));
        if (payload?.account_connected) {
          setOpenAiProviderStatus((prev) => ({
            ...prev,
            accountConnected: true,
            accountAuthMode: String(payload?.account_auth_mode || prev.accountAuthMode || "chatgpt"),
            accountUpdatedAt: String(payload?.account_updated_at || prev.accountUpdatedAt || "")
          }));
        }
      } catch {
        if (!cancelled) {
          setOpenAiAccountSession((prev) => prev);
        }
      }
    }

    refreshAccountSession();
    const interval = setInterval(refreshAccountSession, 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [openAiAccountSession?.id, openAiAccountSession?.running]);

  const projectsById = useMemo(() => {
    const map = new Map();
    for (const project of hubState.projects) {
      map.set(project.id, project);
    }
    return map;
  }, [hubState.projects]);

  function updateCreateForm(patch) {
    setCreateForm((prev) => ({ ...prev, ...patch }));
  }

  function updateProjectDraft(projectId, patch) {
    setProjectDrafts((prev) => ({
      ...prev,
      [projectId]: { ...prev[projectId], ...patch }
    }));
  }

  function markProjectBuilding(projectId) {
    setHubState((prev) => ({
      ...prev,
      projects: (prev.projects || []).map((project) =>
        project.id === projectId
          ? { ...project, build_status: "building", build_error: "" }
          : project
      )
    }));
    setPendingProjectBuilds((prev) => ({ ...prev, [projectId]: true }));
    setOpenBuildLogs((prev) => ({ ...prev, [projectId]: false }));
    setProjectBuildLogs((prev) => ({
      ...prev,
      [projectId]: prev[projectId] || "Preparing project image...\r\n"
    }));
  }

  async function handleCreateProject(event) {
    event.preventDefault();
    try {
      const mounts = buildMountPayload(createForm.defaultVolumes);
      const envVars = buildEnvPayload(createForm.defaultEnvVars);
      const payload = {
        repo_url: createForm.repoUrl.trim(),
        name: createForm.name,
        default_branch: createForm.defaultBranch,
        base_image_mode: createForm.baseImageMode,
        base_image_value: createForm.baseImageValue,
        setup_script: createForm.setupScript,
        default_ro_mounts: mounts.roMounts,
        default_rw_mounts: mounts.rwMounts,
        default_env_vars: envVars
      };
      await fetchJson("/api/projects", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setCreateForm(emptyCreateForm());
      setError("");
      await refreshState();
    } catch (err) {
      setError(err.message || String(err));
    }
  }

  async function persistProjectSettings(projectId) {
    const draft = projectDrafts[projectId];
    if (!draft) {
      throw new Error("Project draft is missing.");
    }
    const mounts = buildMountPayload(draft.defaultVolumes);
    const envVars = buildEnvPayload(draft.defaultEnvVars);
    const payload = {
      base_image_mode: normalizeBaseMode(draft.baseImageMode),
      base_image_value: draft.baseImageValue,
      setup_script: draft.setupScript,
      default_ro_mounts: mounts.roMounts,
      default_rw_mounts: mounts.rwMounts,
      default_env_vars: envVars
    };
    await fetchJson(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  }

  async function handleSaveProjectSettings(projectId) {
    setEditingProjects((prev) => ({ ...prev, [projectId]: false }));
    markProjectBuilding(projectId);
    try {
      await persistProjectSettings(projectId);
      setPendingProjectBuilds((prev) => {
        const next = { ...prev };
        delete next[projectId];
        return next;
      });
      setError("");
      refreshState().catch(() => {});
    } catch (err) {
      setEditingProjects((prev) => ({ ...prev, [projectId]: true }));
      setPendingProjectBuilds((prev) => {
        const next = { ...prev };
        delete next[projectId];
        return next;
      });
      setError(err.message || String(err));
      refreshState().catch(() => {});
    }
  }

  function handleEditProject(project) {
    setProjectDrafts((prev) => ({
      ...prev,
      [project.id]: projectDraftFromProject(project)
    }));
    setEditingProjects((prev) => ({ ...prev, [project.id]: true }));
  }

  function handleCancelProjectEdit(project) {
    setProjectDrafts((prev) => ({
      ...prev,
      [project.id]: projectDraftFromProject(project)
    }));
    setEditingProjects((prev) => ({ ...prev, [project.id]: false }));
  }

  async function handleCreateChat(projectId) {
    const uiId = `pending-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    const project = projectsById.get(projectId);
    const knownServerChatIds = (hubState.chats || [])
      .filter((chat) => String(chat.project_id || "") === String(projectId))
      .map((chat) => chat.id);
    setPendingSessions((prev) => [{
      ui_id: uiId,
      project_id: projectId,
      project_name: project?.name || "Unknown",
      server_chat_id: "",
      known_server_chat_ids: knownServerChatIds,
      seen_on_server: false
    }, ...prev]);
    setActiveTab("chats");
    setCollapsedChats((prev) => ({ ...prev, [uiId]: false }));
    setActiveTerminalChatId(uiId);

    try {
      const response = await fetchJson(`/api/projects/${projectId}/chats/start`, {
        method: "POST"
      });
      const chatId = response?.chat?.id;
      if (chatId) {
        setPendingSessions((prev) =>
          prev.map((session) =>
            session.ui_id === uiId ? { ...session, server_chat_id: chatId } : session
          )
        );
        setPendingChatStarts((prev) => ({ ...prev, [chatId]: true }));
      } else {
        setPendingSessions((prev) => prev.filter((session) => session.ui_id !== uiId));
        setActiveTerminalChatId((current) => (current === uiId ? "" : current));
      }
      setError("");
      refreshState().catch(() => {});
    } catch (err) {
      setPendingSessions((prev) => prev.filter((session) => session.ui_id !== uiId));
      setActiveTerminalChatId((current) => (current === uiId ? "" : current));
      setError(err.message || String(err));
    }
  }

  async function handleDeleteProject(projectId) {
    const project = projectsById.get(projectId);
    const label = project ? project.name : projectId;
    if (!window.confirm(`Delete project '${label}' and all chats?`)) {
      return;
    }
    setHubState((prev) => ({
      ...prev,
      projects: (prev.projects || []).filter((projectItem) => projectItem.id !== projectId),
      chats: (prev.chats || []).filter((chat) => chat.project_id !== projectId)
    }));
    setPendingSessions((prev) => prev.filter((session) => session.project_id !== projectId));
    try {
      await fetchJson(`/api/projects/${projectId}`, { method: "DELETE" });
      setError("");
      refreshState().catch(() => {});
    } catch (err) {
      setError(err.message || String(err));
      refreshState().catch(() => {});
    }
  }

  async function handleStartChat(chatId) {
    setPendingChatStarts((prev) => ({ ...prev, [chatId]: true }));
    setCollapsedChats((prev) => ({ ...prev, [chatId]: false }));
    setActiveTerminalChatId(chatId);
    try {
      await fetchJson(`/api/chats/${chatId}/start`, { method: "POST" });
      setError("");
      refreshState().catch(() => {});
    } catch (err) {
      setPendingChatStarts((prev) => {
        const next = { ...prev };
        delete next[chatId];
        return next;
      });
      setError(err.message || String(err));
      refreshState().catch(() => {});
    }
  }

  async function handleDeleteChat(chatId, uiId = chatId) {
    setHubState((prev) => ({
      ...prev,
      chats: (prev.chats || []).filter((chat) => chat.id !== chatId)
    }));
    setPendingSessions((prev) =>
      prev.filter((session) => session.ui_id !== uiId && session.server_chat_id !== chatId)
    );
    setPendingChatStarts((prev) => {
      const next = { ...prev };
      delete next[chatId];
      return next;
    });
    try {
      await fetchJson(`/api/chats/${chatId}`, { method: "DELETE" });
      setActiveTerminalChatId((current) => (current === uiId || current === chatId ? "" : current));
      setError("");
      refreshState().catch(() => {});
    } catch (err) {
      setError(err.message || String(err));
      refreshState().catch(() => {});
    }
  }

  async function handleBuildProject(projectId) {
    markProjectBuilding(projectId);
    try {
      await persistProjectSettings(projectId);
      setEditingProjects((prev) => ({ ...prev, [projectId]: false }));
      setPendingProjectBuilds((prev) => {
        const next = { ...prev };
        delete next[projectId];
        return next;
      });
      setError("");
      refreshState().catch(() => {});
    } catch (err) {
      setPendingProjectBuilds((prev) => {
        const next = { ...prev };
        delete next[projectId];
        return next;
      });
      setError(err.message || String(err));
      refreshState().catch(() => {});
    }
  }

  async function handleToggleStoredBuildLog(projectId) {
    const currentlyOpen = Boolean(openBuildLogs[projectId]);
    if (currentlyOpen) {
      setOpenBuildLogs((prev) => ({ ...prev, [projectId]: false }));
      return;
    }
    try {
      if (projectStaticLogs[projectId] === undefined) {
        const text = await fetchText(`/api/projects/${projectId}/build-logs`);
        setProjectStaticLogs((prev) => ({ ...prev, [projectId]: text }));
      }
      setOpenBuildLogs((prev) => ({ ...prev, [projectId]: true }));
      setError("");
    } catch (err) {
      setError(err.message || String(err));
    }
  }

  async function handleConnectOpenAi(event) {
    event.preventDefault();
    const apiKey = openAiDraftKey.trim();
    if (!apiKey) {
      setError("OpenAI API key is required.");
      return;
    }

    setOpenAiSaving(true);
    try {
      const payload = await fetchJson("/api/settings/auth/openai/connect", {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey, verify: verifyOpenAiOnSave })
      });
      setOpenAiProviderStatus(normalizeOpenAiProviderStatus(payload?.provider));
      setOpenAiDraftKey("");
      setShowOpenAiDraftKey(false);
      setError("");
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setOpenAiSaving(false);
    }
  }

  async function handleDisconnectOpenAi() {
    setOpenAiDisconnecting(true);
    try {
      const payload = await fetchJson("/api/settings/auth/openai/disconnect", {
        method: "POST"
      });
      setOpenAiProviderStatus(normalizeOpenAiProviderStatus(payload?.provider));
      setOpenAiDraftKey("");
      setShowOpenAiDraftKey(false);
      setError("");
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setOpenAiDisconnecting(false);
    }
  }

  async function handleStartOpenAiAccountLogin(method) {
    setOpenAiAccountStarting(true);
    try {
      const payload = await fetchJson("/api/settings/auth/openai/account/start", {
        method: "POST",
        body: JSON.stringify({ method })
      });
      setOpenAiAccountSession(normalizeOpenAiAccountSession(payload?.session));
      setError("");
      refreshAuthSettings().catch(() => {});
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setOpenAiAccountStarting(false);
    }
  }

  async function handleCancelOpenAiAccountLogin() {
    setOpenAiAccountCancelling(true);
    try {
      const payload = await fetchJson("/api/settings/auth/openai/account/cancel", {
        method: "POST"
      });
      setOpenAiAccountSession(normalizeOpenAiAccountSession(payload?.session));
      setError("");
      refreshAuthSettings().catch(() => {});
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setOpenAiAccountCancelling(false);
    }
  }

  async function handleDisconnectOpenAiAccount() {
    setOpenAiAccountDisconnecting(true);
    try {
      const payload = await fetchJson("/api/settings/auth/openai/account/disconnect", {
        method: "POST"
      });
      setOpenAiProviderStatus(normalizeOpenAiProviderStatus(payload?.provider));
      setError("");
      refreshAuthSettings().catch(() => {});
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setOpenAiAccountDisconnecting(false);
    }
  }

  async function handleForwardOpenAiAccountCallback(event) {
    event.preventDefault();
    const query = extractCallbackQuery(openAiAccountCallbackInput);
    if (!query) {
      setError("Paste the full callback URL (or query string) from the localhost error page.");
      return;
    }
    try {
      const payload = await fetchJson(`/api/settings/auth/openai/account/callback?${query}`);
      setOpenAiAccountSession(normalizeOpenAiAccountSession(payload?.session));
      setOpenAiAccountCallbackInput("");
      setError("");
      refreshAuthSettings().catch(() => {});
    } catch (err) {
      setError(err.message || String(err));
    }
  }

  const chatsByProject = useMemo(() => {
    const byProject = new Map();
    for (const project of hubState.projects) {
      byProject.set(project.id, []);
    }
    const orphanChats = [];
    for (const chat of visibleChats) {
      if (!byProject.has(chat.project_id)) {
        orphanChats.push(chat);
        continue;
      }
      byProject.get(chat.project_id).push(chat);
    }
    return { byProject, orphanChats };
  }, [hubState.projects, visibleChats]);

  const openAiAccountProxyLoginUrl = useMemo(
    () => buildProxiedOpenAiLoginUrl(openAiAccountSession?.loginUrl),
    [openAiAccountSession?.loginUrl]
  );
  const openAiAccountDirectLoginUrl = String(openAiAccountSession?.loginUrl || "").trim();
  const openAiAccountSessionMethod = String(openAiAccountSession?.method || "");
  const openAiAccountLoginInFlight = Boolean(
    openAiAccountSession &&
      ["starting", "running", "waiting_for_browser", "waiting_for_device_code", "callback_received"].includes(
        String(openAiAccountSession.status || "")
      )
  );
  const openAiBrowserCallbackInFlight = openAiAccountLoginInFlight && openAiAccountSessionMethod === "browser_callback";
  const openAiDeviceAuthInFlight = openAiAccountLoginInFlight && openAiAccountSessionMethod === "device_auth";
  const openAiOverallConnected = openAiProviderStatus.accountConnected || openAiProviderStatus.connected;
  const openAiConnectionSummary = openAiProviderStatus.accountConnected && openAiProviderStatus.connected
    ? "Connected with OpenAI account and API key."
    : openAiProviderStatus.accountConnected
      ? "Connected with OpenAI account."
      : openAiProviderStatus.connected
        ? "Connected with API key."
        : "Not connected yet. Expand this section and choose one login method.";

  useEffect(() => {
    if (!openAiAuthLoaded || openAiCardExpansionInitialized) {
      return;
    }
    setOpenAiCardExpanded(!openAiOverallConnected);
    setOpenAiCardExpansionInitialized(true);
  }, [openAiAuthLoaded, openAiCardExpansionInitialized, openAiOverallConnected]);

  useEffect(() => {
    if (openAiAccountLoginInFlight) {
      setOpenAiCardExpanded(true);
    }
  }, [openAiAccountLoginInFlight]);

  return (
    <div className="app-root">
      <header className="app-header">
        <div className="header-row">
          <div>
            <h1>Agent Hub</h1>
            <p>Project-level workspaces, one cloned directory per chat.</p>
          </div>
          <div className="tab-row">
            <button
              type="button"
              className={`tab-button ${activeTab === "projects" ? "active" : ""}`}
              onClick={() => setActiveTab("projects")}
            >
              Projects
            </button>
            <button
              type="button"
              className={`tab-button ${activeTab === "chats" ? "active" : ""}`}
              onClick={() => setActiveTab("chats")}
            >
              Chats
            </button>
            <button
              type="button"
              className={`tab-button ${activeTab === "settings" ? "active" : ""}`}
              onClick={() => setActiveTab("settings")}
            >
              Settings
            </button>
          </div>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <main className="layout">
        {activeTab === "projects" ? (
          <section className="panel">
            <h2>Add Project</h2>
            <form className="stack" onSubmit={handleCreateProject}>
              <input
                required
                value={createForm.repoUrl}
                onChange={(event) => updateCreateForm({ repoUrl: event.target.value })}
                placeholder="git@github.com:org/repo.git or https://..."
              />
              <div className="row two">
                <input
                  value={createForm.name}
                  onChange={(event) => updateCreateForm({ name: event.target.value })}
                  placeholder="Optional project name"
                />
                <input
                  value={createForm.defaultBranch}
                  onChange={(event) => updateCreateForm({ defaultBranch: event.target.value })}
                  placeholder="Default branch (optional)"
                />
              </div>
              <div className="row two">
                <select
                  value={createForm.baseImageMode}
                  onChange={(event) => updateCreateForm({ baseImageMode: event.target.value })}
                >
                  <option value="tag">Docker image tag</option>
                  <option value="repo_path">Repo Dockerfile/path</option>
                </select>
                <input
                  value={createForm.baseImageValue}
                  onChange={(event) => updateCreateForm({ baseImageValue: event.target.value })}
                  placeholder={baseInputPlaceholder(createForm.baseImageMode)}
                />
              </div>
              <textarea
                className="script-input"
                value={createForm.setupScript}
                onChange={(event) => updateCreateForm({ setupScript: event.target.value })}
                placeholder={
                  "Setup script (one command per line; runs in container with checked-out project as working directory)\n" +
                  "example:\nuv sync\nuv run python -m pip install -e ."
                }
              />

              <div className="label">Default volumes for new chats</div>
              <VolumeEditor rows={createForm.defaultVolumes} onChange={(rows) => updateCreateForm({ defaultVolumes: rows })} />

              <div className="label">Default environment variables for new chats</div>
              <EnvVarEditor rows={createForm.defaultEnvVars} onChange={(rows) => updateCreateForm({ defaultEnvVars: rows })} />

              <button type="submit" className="btn-primary">
                Add project
              </button>
            </form>

            <h2 className="section-title">Projects</h2>
            <div className="stack">
              {hubState.projects.length === 0 ? <div className="empty">No projects yet.</div> : null}
              {hubState.projects.map((project) => {
                const draft = projectDrafts[project.id] || projectDraftFromProject(project);
                const setupCommands = String(project.setup_script || "")
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean);
                const defaultRoMounts = project.default_ro_mounts || [];
                const defaultRwMounts = project.default_rw_mounts || [];
                const defaultEnvVars = project.default_env_vars || [];
                const defaultVolumeCount =
                  defaultRoMounts.length + defaultRwMounts.length;
                const defaultEnvCount = defaultEnvVars.length;
                const buildStatus = String(project.build_status || "pending");
                const statusInfo = projectStatusInfo(buildStatus);
                const isBuilding = buildStatus === "building" || Boolean(pendingProjectBuilds[project.id]);
                const canStartChat = buildStatus === "ready";
                const canShowStoredLogButton = buildStatus === "ready" || buildStatus === "failed";
                const isEditing = Boolean(editingProjects[project.id]);
                const isStoredLogOpen = Boolean(openBuildLogs[project.id]);
                const storedLogText = projectStaticLogs[project.id];

                return (
                  <article className="card project-card" key={project.id}>
                    <div className="project-head">
                      <h3>{project.name}</h3>
                      {!isEditing ? (
                        <button
                          type="button"
                          className="icon-button"
                          title="Edit project settings"
                          aria-label={`Edit ${project.name}`}
                          onClick={() => handleEditProject(project)}
                        >
                          ✎
                        </button>
                      ) : null}
                    </div>
                    <div className="meta">ID: {project.id}</div>
                    <div className="meta">Repo: {project.repo_url}</div>
                    <div className="meta">Branch: {project.default_branch || "master"}</div>
                    <div className="meta">Status: <span className={`project-build-state ${statusInfo.key}`}>{statusInfo.label}</span></div>
                    <div className="meta">
                      Base image source:{" "}
                      {project.base_image_value
                        ? `${baseModeLabel(normalizeBaseMode(project.base_image_mode))}: ${project.base_image_value}`
                        : "Default agent_cli base image"}
                    </div>
                    {project.setup_snapshot_image ? (
                      <div className="meta">Setup snapshot image: {project.setup_snapshot_image}</div>
                    ) : null}
                    {project.build_error ? <div className="meta build-error">{project.build_error}</div> : null}
                    {setupCommands.length > 0 ? (
                      <details className="details-block">
                        <summary className="details-summary">Setup commands ({setupCommands.length})</summary>
                        <pre className="log-box details-log">{setupCommands.join("\n")}</pre>
                      </details>
                    ) : null}
                    {defaultVolumeCount > 0 ? (
                      <details className="details-block">
                        <summary className="details-summary">Default volumes ({defaultVolumeCount})</summary>
                        <div className="details-list">
                          {defaultRoMounts.map((mount, idx) => (
                            <div className="meta" key={`ro-${project.id}-${idx}`}>read-only: {mount}</div>
                          ))}
                          {defaultRwMounts.map((mount, idx) => (
                            <div className="meta" key={`rw-${project.id}-${idx}`}>read-write: {mount}</div>
                          ))}
                        </div>
                      </details>
                    ) : null}
                    {defaultEnvCount > 0 ? (
                      <details className="details-block">
                        <summary className="details-summary">Default environment variables ({defaultEnvCount})</summary>
                        <div className="details-list">
                          {defaultEnvVars.map((entry, idx) => (
                            <div className="meta" key={`env-${project.id}-${idx}`}>{entry}</div>
                          ))}
                        </div>
                      </details>
                    ) : null}

                    <div className="stack compact">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={!canStartChat && isBuilding}
                        onClick={() => (canStartChat ? handleCreateChat(project.id) : handleBuildProject(project.id))}
                      >
                        {canStartChat
                          ? "New chat"
                          : isBuilding
                            ? <SpinnerLabel text="Building image..." />
                            : "Build"}
                      </button>
                      {isBuilding ? (
                        <ProjectBuildTerminal
                          text={projectBuildLogs[project.id] || "Preparing project image...\r\n"}
                        />
                      ) : null}
                      {canShowStoredLogButton ? (
                        <div className="actions">
                          <button
                            type="button"
                            className="btn-secondary btn-small build-log-toggle"
                            onClick={() => handleToggleStoredBuildLog(project.id)}
                          >
                            {isStoredLogOpen ? "Hide stored build log" : "Show stored build log"}
                          </button>
                        </div>
                      ) : null}
                      {canShowStoredLogButton && isStoredLogOpen ? (
                        <pre className="log-box">
                          {storedLogText && storedLogText.trim()
                            ? storedLogText
                            : "No stored build log found for this project yet."}
                        </pre>
                      ) : null}

                      {isEditing ? (
                        <>
                          <div className="row two">
                            <select
                              value={draft.baseImageMode}
                              onChange={(event) =>
                                updateProjectDraft(project.id, { baseImageMode: event.target.value })
                              }
                            >
                              <option value="tag">Docker image tag</option>
                              <option value="repo_path">Repo Dockerfile/path</option>
                            </select>
                            <input
                              value={draft.baseImageValue}
                              onChange={(event) =>
                                updateProjectDraft(project.id, { baseImageValue: event.target.value })
                              }
                              placeholder={baseInputPlaceholder(draft.baseImageMode)}
                            />
                          </div>

                          <textarea
                            className="script-input"
                            value={draft.setupScript}
                            onChange={(event) =>
                              updateProjectDraft(project.id, { setupScript: event.target.value })
                            }
                            placeholder="One setup command per line."
                          />

                          <div className="label">Default volumes for new chats</div>
                          <VolumeEditor
                            rows={draft.defaultVolumes}
                            onChange={(rows) => updateProjectDraft(project.id, { defaultVolumes: rows })}
                          />

                          <div className="label">Default environment variables for new chats</div>
                          <EnvVarEditor
                            rows={draft.defaultEnvVars}
                            onChange={(rows) => updateProjectDraft(project.id, { defaultEnvVars: rows })}
                          />

                          <div className="actions">
                            <button
                              type="button"
                              className="btn-primary"
                              onClick={() => handleSaveProjectSettings(project.id)}
                            >
                              Save project settings
                            </button>
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={() => handleCancelProjectEdit(project)}
                            >
                              Cancel
                            </button>
                          </div>
                        </>
                      ) : null}

                      <div className="actions">
                        <button type="button" className="btn-danger" onClick={() => handleDeleteProject(project.id)}>
                          Delete project
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ) : activeTab === "chats" ? (
          <section className="panel">
            <h2>Chats</h2>
            <div className="stack">
              {hubState.projects.length === 0 ? <div className="empty">No projects yet.</div> : null}
              {hubState.projects.map((project) => {
                const projectChats = chatsByProject.byProject.get(project.id) || [];
                const buildStatus = String(project.build_status || "pending");
                const statusInfo = projectStatusInfo(buildStatus);
                const canStartChat = buildStatus === "ready";
                const isBuilding = buildStatus === "building" || Boolean(pendingProjectBuilds[project.id]);
                return (
                  <article className="card project-chat-group" key={`group-${project.id}`}>
                    <div className="project-head">
                      <h3>{project.name}</h3>
                    </div>
                    <div className="meta">Status: <span className={`project-build-state ${statusInfo.key}`}>{statusInfo.label}</span></div>
                    <div className="actions">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={!canStartChat && isBuilding}
                        onClick={() => (canStartChat ? handleCreateChat(project.id) : handleBuildProject(project.id))}
                      >
                        {canStartChat
                          ? "New chat"
                          : isBuilding
                            ? <SpinnerLabel text="Building image..." />
                            : "Build"}
                      </button>
                    </div>

                    <div className="stack compact">
                      {projectChats.length === 0 ? <div className="empty">No chats yet for this project.</div> : null}
                      {projectChats.map((chat) => {
                        const resolvedChatId = String(chat.server_chat_id || chat.id || "");
                        const hasServerChat = Boolean(chat.server_chat_id || !String(chat.id || "").startsWith("pending-"));
                        const isRunning = Boolean(chat.is_running);
                        const isStarting = Boolean(
                          pendingChatStarts[resolvedChatId] || chat.is_pending_start || String(chat.status || "") === "starting"
                        );
                        const volumeCount = (chat.ro_mounts || []).length + (chat.rw_mounts || []).length;
                        const envCount = (chat.env_vars || []).length;
                        const isActiveTerminal = activeTerminalChatId === chat.id;
                        const collapsed = collapsedChats[chat.id] ?? true;
                        return (
                          <article className="card" key={chat.id}>
                            <div
                              className="chat-card-header"
                              role="button"
                              tabIndex={0}
                              onClick={() => setCollapsedChats((prev) => ({ ...prev, [chat.id]: !collapsed }))}
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  setCollapsedChats((prev) => ({ ...prev, [chat.id]: !collapsed }));
                                }
                              }}
                            >
                              <h3>{chat.display_name || chat.name}</h3>
                              <div className="meta">
                                <span className={`status ${isRunning ? "running" : isStarting ? "starting" : "stopped"}`}>
                                  {isRunning ? chat.status : isStarting ? "starting" : chat.status}
                                </span>{" "}
                                {chat.project_name}
                              </div>
                              {collapsed ? (
                                <div className="meta">
                                  {isStarting
                                    ? "Starting chat and preparing terminal..."
                                    : chat.display_subtitle || "No recent assistant summary yet."}
                                </div>
                              ) : null}
                            </div>
                            {!collapsed ? (
                              <>
                                <div className="meta">Chat ID: {resolvedChatId || "starting..."}</div>
                                <div className="meta">Workspace: {chat.workspace}</div>
                                <div className="meta">Container folder: {chat.container_workspace || "not started yet"}</div>
                                {chat.setup_snapshot_image ? (
                                  <div className="meta">Setup snapshot image: {chat.setup_snapshot_image}</div>
                                ) : null}
                                <div className="meta">Volumes: {volumeCount} | Env vars: {envCount}</div>
                              </>
                            ) : null}

                            <div className="stack compact">
                              <div className="actions chat-actions">
                                {!isRunning && !isStarting && hasServerChat ? (
                                  <button
                                    type="button"
                                    className="btn-primary chat-primary-action"
                                    onClick={() => handleStartChat(resolvedChatId)}
                                  >
                                    Start
                                  </button>
                                ) : null}
                                {isStarting ? (
                                  <button type="button" className="btn-primary chat-primary-action" disabled>
                                    Starting...
                                  </button>
                                ) : null}
                                {isRunning ? (
                                  <button
                                    type="button"
                                    className="btn-primary chat-primary-action"
                                    onClick={() => {
                                      setActiveTerminalChatId(chat.id);
                                      setCollapsedChats((prev) => ({ ...prev, [chat.id]: false }));
                                    }}
                                  >
                                    {isActiveTerminal ? "Connected" : "Connect"}
                                  </button>
                                ) : null}
                                <button
                                  type="button"
                                  className="btn-danger"
                                  onClick={() => {
                                    if (!hasServerChat) {
                                      setPendingSessions((prev) => prev.filter((session) => session.ui_id !== chat.id));
                                      setActiveTerminalChatId((current) => (current === chat.id ? "" : current));
                                      return;
                                    }
                                    handleDeleteChat(resolvedChatId, chat.id);
                                  }}
                                >
                                  Delete
                                </button>
                              </div>

                              {!collapsed && isActiveTerminal ? (
                                isStarting && !isRunning ? (
                                  <div className="terminal-shell chat-terminal-shell chat-terminal-placeholder">
                                    <div className="terminal-overlay">
                                      <span className="inline-spinner" aria-hidden="true" />
                                    </div>
                                  </div>
                                ) : (
                                  <ChatTerminal chatId={resolvedChatId} running={isRunning} />
                                )
                              ) : null}
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </article>
                );
              })}
              {chatsByProject.orphanChats.length > 0 ? (
                <article className="card project-chat-group" key="group-orphan">
                  <div className="project-head">
                    <h3>Unknown project</h3>
                  </div>
                  <div className="stack compact">
                    {chatsByProject.orphanChats.map((chat) => {
                      const resolvedChatId = String(chat.server_chat_id || chat.id || "");
                      const hasServerChat = Boolean(chat.server_chat_id || !String(chat.id || "").startsWith("pending-"));
                      const isRunning = Boolean(chat.is_running);
                      const isStarting = Boolean(
                        pendingChatStarts[resolvedChatId] || chat.is_pending_start || String(chat.status || "") === "starting"
                      );
                      const isActiveTerminal = activeTerminalChatId === chat.id;
                      const collapsed = collapsedChats[chat.id] ?? true;
                      return (
                        <article className="card" key={chat.id}>
                          <div
                            className="chat-card-header"
                            role="button"
                            tabIndex={0}
                            onClick={() => setCollapsedChats((prev) => ({ ...prev, [chat.id]: !collapsed }))}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                setCollapsedChats((prev) => ({ ...prev, [chat.id]: !collapsed }));
                              }
                            }}
                          >
                            <h3>{chat.display_name || chat.name}</h3>
                            <div className="meta">
                              <span className={`status ${isRunning ? "running" : isStarting ? "starting" : "stopped"}`}>
                                {isRunning ? chat.status : isStarting ? "starting" : chat.status}
                              </span>
                            </div>
                            {collapsed ? (
                              <div className="meta">
                                {isStarting
                                  ? "Starting chat and preparing terminal..."
                                  : chat.display_subtitle || "No recent assistant summary yet."}
                              </div>
                            ) : null}
                          </div>
                          <div className="stack compact">
                            <div className="actions chat-actions">
                              {!isRunning && !isStarting && hasServerChat ? (
                                <button
                                  type="button"
                                  className="btn-primary chat-primary-action"
                                  onClick={() => handleStartChat(resolvedChatId)}
                                >
                                  Start
                                </button>
                              ) : null}
                              {isStarting ? (
                                <button type="button" className="btn-primary chat-primary-action" disabled>
                                  Starting...
                                </button>
                              ) : null}
                              {isRunning ? (
                                <button
                                  type="button"
                                  className="btn-primary chat-primary-action"
                                  onClick={() => {
                                    setActiveTerminalChatId(chat.id);
                                    setCollapsedChats((prev) => ({ ...prev, [chat.id]: false }));
                                  }}
                                >
                                  {isActiveTerminal ? "Connected" : "Connect"}
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="btn-danger"
                                onClick={() => {
                                  if (!hasServerChat) {
                                    setPendingSessions((prev) => prev.filter((session) => session.ui_id !== chat.id));
                                    setActiveTerminalChatId((current) => (current === chat.id ? "" : current));
                                    return;
                                  }
                                  handleDeleteChat(resolvedChatId, chat.id);
                                }}
                              >
                                Delete
                              </button>
                            </div>
                            {!collapsed && isActiveTerminal ? (
                              isStarting && !isRunning ? (
                                <div className="terminal-shell chat-terminal-shell chat-terminal-placeholder">
                                  <div className="terminal-overlay">
                                    <span className="inline-spinner" aria-hidden="true" />
                                  </div>
                                </div>
                              ) : (
                                <ChatTerminal chatId={resolvedChatId} running={isRunning} />
                              )
                            ) : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </article>
              ) : null}
            </div>
          </section>
        ) : (
          <section className="panel">
            <h2>Settings</h2>
            <article className="card auth-provider-card">
              <div className="project-head">
                <h3>OpenAI</h3>
                <div className="connection-summary">
                  <span className={`connection-pill ${openAiOverallConnected ? "connected" : "disconnected"}`}>
                    {openAiOverallConnected ? "connected" : "not connected"}
                  </span>
                  <button
                    type="button"
                    className="btn-secondary btn-small"
                    onClick={() => {
                      setOpenAiCardExpansionInitialized(true);
                      setOpenAiCardExpanded((expanded) => !expanded);
                    }}
                  >
                    {openAiCardExpanded ? "Hide details" : "Show details"}
                  </button>
                </div>
              </div>
              <p className="meta">{openAiConnectionSummary}</p>
              {openAiCardExpanded ? (
                <>
                  <p className="meta">
                    Connect with either your OpenAI account or an API key. New chat instances and project setup runs will use
                    whichever credential is available.
                  </p>
                  <div className="actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={handleCancelOpenAiAccountLogin}
                      disabled={!openAiAccountLoginInFlight || openAiAccountCancelling}
                    >
                      {openAiAccountCancelling ? <SpinnerLabel text="Cancelling..." /> : "Cancel account login"}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={handleDisconnectOpenAiAccount}
                      disabled={
                        !openAiProviderStatus.accountConnected ||
                        openAiAccountDisconnecting ||
                        openAiAccountLoginInFlight
                      }
                    >
                      {openAiAccountDisconnecting ? <SpinnerLabel text="Disconnecting..." /> : "Disconnect account"}
                    </button>
                  </div>
                  {openAiAccountSession ? (
                    <div className="stack compact">
                      <div className="meta">
                        Account login status: {openAiAccountSession.status || "starting"}
                      </div>
                      {openAiAccountSession.error ? (
                        <div className="meta build-error">{openAiAccountSession.error}</div>
                      ) : null}
                      {openAiAccountSession.logTail ? (
                        <pre className="log-box settings-auth-log">{openAiAccountSession.logTail}</pre>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="settings-auth-block">
                    <h4>Login with OpenAI account (browser)</h4>
                    <ol className="settings-auth-help-list">
                      <li>Click <strong>Start browser login</strong>.</li>
                      <li>Click <strong>Open auth page</strong> and complete sign-in and consent.</li>
                      <li>If the browser ends on a localhost error page, copy the full URL and submit it below.</li>
                    </ol>
                    <div className="meta">
                      Account mode: {openAiProviderStatus.accountAuthMode || "none"}
                    </div>
                    <div className="meta">
                      Last account update: {formatTimestamp(openAiProviderStatus.accountUpdatedAt)}
                    </div>
                    <div className="actions">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => handleStartOpenAiAccountLogin("browser_callback")}
                        disabled={
                          openAiAccountStarting ||
                          openAiAccountCancelling ||
                          openAiAccountDisconnecting ||
                          openAiBrowserCallbackInFlight
                        }
                      >
                        {openAiAccountStarting
                          ? <SpinnerLabel text="Starting login..." />
                          : openAiBrowserCallbackInFlight
                            ? "Browser login running"
                            : "Start browser login"}
                      </button>
                      {openAiAccountDirectLoginUrl && openAiAccountSessionMethod === "browser_callback" ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => window.open(openAiAccountProxyLoginUrl, "_blank", "noopener,noreferrer")}
                        >
                          Open auth page
                        </button>
                      ) : null}
                      {openAiAccountDirectLoginUrl &&
                      openAiAccountSessionMethod === "browser_callback" &&
                      openAiAccountProxyLoginUrl !== openAiAccountDirectLoginUrl ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => window.open(openAiAccountDirectLoginUrl, "_blank", "noopener,noreferrer")}
                        >
                          Open direct localhost URL
                        </button>
                      ) : null}
                    </div>
                    {openAiAccountSessionMethod === "browser_callback" ? (
                      <div className="stack compact">
                        <p className="meta">
                          Local callback URL:{" "}
                          <code>{openAiAccountSession?.localCallbackUrl || "http://localhost:1455/auth/callback"}</code>
                        </p>
                        <form className="stack compact" onSubmit={handleForwardOpenAiAccountCallback}>
                          <div className="settings-auth-input-row">
                            <input
                              value={openAiAccountCallbackInput}
                              onChange={(event) => setOpenAiAccountCallbackInput(event.target.value)}
                              placeholder="Paste callback URL (or query like code=...&state=...)"
                              autoComplete="off"
                              spellCheck={false}
                            />
                          </div>
                          <div className="actions">
                            <button type="submit" className="btn-secondary">
                              Submit callback URL
                            </button>
                          </div>
                        </form>
                      </div>
                    ) : null}
                  </div>

                  <div className="settings-auth-block">
                    <h4>Login with OpenAI account (device code)</h4>
                    <ol className="settings-auth-help-list">
                      <li>Click <strong>Start device code login</strong>.</li>
                      <li>Click <strong>Open device auth page</strong>.</li>
                      <li>Enter the one-time code shown below, then approve access.</li>
                    </ol>
                    <div className="actions">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => handleStartOpenAiAccountLogin("device_auth")}
                        disabled={
                          openAiAccountStarting ||
                          openAiAccountCancelling ||
                          openAiAccountDisconnecting ||
                          openAiDeviceAuthInFlight
                        }
                      >
                        {openAiAccountStarting
                          ? <SpinnerLabel text="Starting login..." />
                          : openAiDeviceAuthInFlight
                            ? "Device login running"
                            : "Start device code login"}
                      </button>
                      {openAiAccountDirectLoginUrl && openAiAccountSessionMethod === "device_auth" ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => window.open(openAiAccountDirectLoginUrl, "_blank", "noopener,noreferrer")}
                        >
                          Open device auth page
                        </button>
                      ) : null}
                    </div>
                    {openAiAccountSessionMethod === "device_auth" && openAiAccountSession?.deviceCode ? (
                      <p className="meta">
                        Enter one-time code: <code>{openAiAccountSession.deviceCode}</code>
                      </p>
                    ) : null}
                  </div>

                  <div className="settings-auth-block">
                    <h4>Login with API key</h4>
                    <div className="settings-auth-help">
                      <p className="meta settings-auth-help-title">How to get an OpenAI API key</p>
                      <ol className="settings-auth-help-list">
                        <li>
                          Open{" "}
                          <a
                            href="https://platform.openai.com/api-keys"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            https://platform.openai.com/api-keys
                          </a>
                          {" "}and sign in.
                        </li>
                        <li>Create a new secret key.</li>
                        <li>Copy the key immediately (it may only be shown once).</li>
                        <li>Paste it here and keep &quot;Verify with OpenAI before saving&quot; enabled.</li>
                      </ol>
                    </div>
                    <div className="meta">Saved key: {openAiProviderStatus.keyHint || "none"}</div>
                    <div className="meta">Last updated: {formatTimestamp(openAiProviderStatus.updatedAt)}</div>

                    <form className="stack compact" onSubmit={handleConnectOpenAi}>
                      <div className="settings-auth-input-row">
                        <input
                          type={showOpenAiDraftKey ? "text" : "password"}
                          value={openAiDraftKey}
                          onChange={(event) => setOpenAiDraftKey(event.target.value)}
                          placeholder="Paste OpenAI API key (sk-...)"
                          autoComplete="off"
                          spellCheck={false}
                        />
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => setShowOpenAiDraftKey((prev) => !prev)}
                        >
                          {showOpenAiDraftKey ? "Hide" : "Show"}
                        </button>
                      </div>
                      <label className="settings-checkbox-row">
                        <input
                          type="checkbox"
                          checked={verifyOpenAiOnSave}
                          onChange={(event) => setVerifyOpenAiOnSave(event.target.checked)}
                        />
                        <span>Verify with OpenAI before saving</span>
                      </label>
                      <div className="actions">
                        <button
                          type="submit"
                          className="btn-primary"
                          disabled={openAiSaving || openAiDisconnecting}
                        >
                          {openAiSaving
                            ? <SpinnerLabel text={verifyOpenAiOnSave ? "Verifying..." : "Saving..."} />
                            : "Connect API key"}
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={!openAiProviderStatus.connected || openAiSaving || openAiDisconnecting}
                          onClick={handleDisconnectOpenAi}
                        >
                          {openAiDisconnecting ? <SpinnerLabel text="Disconnecting..." /> : "Disconnect API key"}
                        </button>
                      </div>
                    </form>
                  </div>
                  <p className="meta settings-auth-note">
                    API keys are stored only on this machine with restricted file permissions and are never returned by the API
                    after save.
                  </p>
                </>
              ) : null}
            </article>
          </section>
        )}
      </main>
    </div>
  );
}

export default function App() {
  if (window.location.pathname === "/openai-auth/callback") {
    return <OpenAiAuthCallbackPage />;
  }
  return <HubApp />;
}
