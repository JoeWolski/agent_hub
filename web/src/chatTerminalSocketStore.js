const WS_CONNECTING_STATE = typeof WebSocket !== "undefined" ? WebSocket.CONNECTING : 0;
const WS_OPEN_STATE = typeof WebSocket !== "undefined" ? WebSocket.OPEN : 1;

function normalizeChatId(rawChatId) {
  return String(rawChatId || "").trim();
}

function defaultTerminalSocketUrl(chatId) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/api/chats/${chatId}/terminal`;
}

function defaultCreateWebSocket(url) {
  return new WebSocket(url);
}

function defaultSetTimeout(callback, delayMs) {
  return window.setTimeout(callback, delayMs);
}

function defaultClearTimeout(timerId) {
  window.clearTimeout(timerId);
}

function trimTerminalBuffer(text, limitChars) {
  if (typeof text !== "string") {
    return "";
  }
  const limit = Math.max(1, Number(limitChars) || 1);
  if (text.length <= limit) {
    return text;
  }
  return text.slice(text.length - limit);
}

export function createChatTerminalSocketStore({
  makeSocketUrl = defaultTerminalSocketUrl,
  createWebSocket = defaultCreateWebSocket,
  reconnectDelayMs = 800,
  maxBufferedChars = 2_000_000,
  setTimeoutFn = defaultSetTimeout,
  clearTimeoutFn = defaultClearTimeout
} = {}) {
  const sessions = new Map();

  function ensureSession(chatId) {
    const normalizedChatId = normalizeChatId(chatId);
    if (!normalizedChatId) {
      return null;
    }
    if (sessions.has(normalizedChatId)) {
      return sessions.get(normalizedChatId);
    }
    const session = {
      chatId: normalizedChatId,
      running: false,
      status: "offline",
      socket: null,
      socketListeners: null,
      reconnectTimer: null,
      listeners: new Set(),
      buffer: "",
      sentCols: 0,
      sentRows: 0
    };
    sessions.set(normalizedChatId, session);
    return session;
  }

  function setStatus(session, nextStatus) {
    const normalizedStatus = String(nextStatus || "unknown").toLowerCase();
    if (session.status === normalizedStatus) {
      return;
    }
    session.status = normalizedStatus;
    for (const listener of session.listeners) {
      if (typeof listener.onStatus === "function") {
        listener.onStatus(normalizedStatus);
      }
    }
  }

  function clearReconnectTimer(session) {
    if (session.reconnectTimer === null) {
      return;
    }
    clearTimeoutFn(session.reconnectTimer);
    session.reconnectTimer = null;
  }

  function removeSocketListeners(session, socket) {
    const activeListeners = session.socketListeners;
    if (!activeListeners || activeListeners.socket !== socket) {
      return;
    }
    socket.removeEventListener("open", activeListeners.onOpen);
    socket.removeEventListener("message", activeListeners.onMessage);
    socket.removeEventListener("close", activeListeners.onClose);
    socket.removeEventListener("error", activeListeners.onError);
    if (session.socketListeners === activeListeners) {
      session.socketListeners = null;
    }
  }

  function closeSocket(session) {
    clearReconnectTimer(session);
    const socket = session.socket;
    if (!socket) {
      session.sentCols = 0;
      session.sentRows = 0;
      return;
    }
    removeSocketListeners(session, socket);
    if (socket.readyState === WS_CONNECTING_STATE || socket.readyState === WS_OPEN_STATE) {
      socket.close();
    }
    if (session.socket === socket) {
      session.socket = null;
    }
    session.sentCols = 0;
    session.sentRows = 0;
  }

  function maybeDeleteSession(session) {
    if (session.running) {
      return;
    }
    if (session.listeners.size > 0) {
      return;
    }
    clearReconnectTimer(session);
    if (session.socket) {
      closeSocket(session);
    }
    sessions.delete(session.chatId);
  }

  function appendChunk(session, chunk) {
    if (typeof chunk !== "string" || !chunk) {
      return;
    }
    session.buffer = trimTerminalBuffer(`${session.buffer}${chunk}`, maxBufferedChars);
    for (const listener of session.listeners) {
      if (typeof listener.onData === "function") {
        listener.onData(chunk);
      }
    }
  }

  function scheduleReconnect(session) {
    if (!session.running || session.reconnectTimer !== null) {
      return;
    }
    session.reconnectTimer = setTimeoutFn(() => {
      session.reconnectTimer = null;
      connectSession(session);
    }, reconnectDelayMs);
  }

  function connectSession(session) {
    if (!session.running) {
      return;
    }
    if (session.socket && (
      session.socket.readyState === WS_CONNECTING_STATE || session.socket.readyState === WS_OPEN_STATE
    )) {
      return;
    }

    clearReconnectTimer(session);
    setStatus(session, "connecting");

    const socket = createWebSocket(makeSocketUrl(session.chatId));
    session.socket = socket;
    session.sentCols = 0;
    session.sentRows = 0;

    const onOpen = () => {
      if (session.socket !== socket) {
        return;
      }
      session.sentCols = 0;
      session.sentRows = 0;
      setStatus(session, "connected");
    };
    const onMessage = (event) => {
      if (session.socket !== socket) {
        return;
      }
      if (typeof event?.data !== "string") {
        return;
      }
      appendChunk(session, event.data);
    };
    const onClose = () => {
      if (session.socket !== socket) {
        return;
      }
      removeSocketListeners(session, socket);
      session.socket = null;
      session.sentCols = 0;
      session.sentRows = 0;
      if (!session.running) {
        setStatus(session, "offline");
        maybeDeleteSession(session);
        return;
      }
      setStatus(session, "closed");
      scheduleReconnect(session);
    };
    const onError = () => {
      if (session.socket !== socket) {
        return;
      }
      setStatus(session, "error");
      if (socket.readyState === WS_CONNECTING_STATE || socket.readyState === WS_OPEN_STATE) {
        socket.close();
      }
    };

    session.socketListeners = { socket, onOpen, onMessage, onClose, onError };
    socket.addEventListener("open", onOpen);
    socket.addEventListener("message", onMessage);
    socket.addEventListener("close", onClose);
    socket.addEventListener("error", onError);
  }

  function sendPayload(session, payload) {
    const socket = session?.socket;
    if (!socket || socket.readyState !== WS_OPEN_STATE) {
      return false;
    }
    socket.send(JSON.stringify(payload));
    return true;
  }

  function setRunning(chatId, running) {
    const normalizedChatId = normalizeChatId(chatId);
    if (!normalizedChatId) {
      return;
    }
    const shouldRun = Boolean(running);
    const existingSession = sessions.get(normalizedChatId);
    const session = existingSession || (shouldRun ? ensureSession(normalizedChatId) : null);
    if (!session) {
      return;
    }
    if (session.running === shouldRun) {
      if (shouldRun) {
        connectSession(session);
      } else {
        setStatus(session, "offline");
        maybeDeleteSession(session);
      }
      return;
    }

    session.running = shouldRun;
    if (shouldRun) {
      connectSession(session);
      return;
    }

    closeSocket(session);
    setStatus(session, "offline");
    maybeDeleteSession(session);
  }

  function subscribe(chatId, listener = {}) {
    const session = ensureSession(chatId);
    if (!session) {
      return () => {};
    }
    session.listeners.add(listener);
    if (typeof listener.onStatus === "function") {
      listener.onStatus(session.status);
    }
    if (session.buffer && typeof listener.onBacklog === "function") {
      listener.onBacklog(session.buffer);
    }
    if (session.running) {
      connectSession(session);
    }
    return () => {
      session.listeners.delete(listener);
      maybeDeleteSession(session);
    };
  }

  function sendInput(chatId, rawText) {
    const session = sessions.get(normalizeChatId(chatId));
    const text = String(rawText || "");
    if (!session || !text) {
      return false;
    }
    return sendPayload(session, { type: "input", data: text });
  }

  function sendSubmit(chatId) {
    const session = sessions.get(normalizeChatId(chatId));
    if (!session) {
      return false;
    }
    return sendPayload(session, { type: "submit" });
  }

  function sendResize(chatId, cols, rows, { force = false } = {}) {
    const session = sessions.get(normalizeChatId(chatId));
    if (!session) {
      return false;
    }
    const nextCols = Math.max(1, Number(cols) || 1);
    const nextRows = Math.max(1, Number(rows) || 1);
    if (!force && nextCols === session.sentCols && nextRows === session.sentRows) {
      return true;
    }
    const sent = sendPayload(session, { type: "resize", cols: nextCols, rows: nextRows });
    if (!sent) {
      return false;
    }
    session.sentCols = nextCols;
    session.sentRows = nextRows;
    return true;
  }

  function syncRunningStates(chatStateEntries) {
    const desiredRunningStates = new Map();
    for (const entry of chatStateEntries || []) {
      if (!Array.isArray(entry) || entry.length < 2) {
        continue;
      }
      const chatId = normalizeChatId(entry[0]);
      if (!chatId) {
        continue;
      }
      desiredRunningStates.set(chatId, Boolean(entry[1]));
    }
    for (const [chatId, shouldRun] of desiredRunningStates.entries()) {
      setRunning(chatId, shouldRun);
    }
    for (const chatId of Array.from(sessions.keys())) {
      if (desiredRunningStates.has(chatId)) {
        continue;
      }
      setRunning(chatId, false);
    }
  }

  function disposeAll() {
    for (const session of sessions.values()) {
      session.running = false;
      closeSocket(session);
      setStatus(session, "offline");
    }
    sessions.clear();
  }

  function debugSnapshot() {
    return Array.from(sessions.values()).map((session) => ({
      chatId: session.chatId,
      running: session.running,
      status: session.status,
      listenerCount: session.listeners.size,
      hasSocket: Boolean(session.socket),
      reconnectScheduled: session.reconnectTimer !== null,
      bufferedChars: session.buffer.length
    }));
  }

  return {
    subscribe,
    setRunning,
    sendInput,
    sendSubmit,
    sendResize,
    syncRunningStates,
    disposeAll,
    debugSnapshot
  };
}

export const chatTerminalSocketStore = createChatTerminalSocketStore();
