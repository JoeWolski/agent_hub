export const PENDING_SESSION_STALE_MS = 30_000;
export const PENDING_CHAT_START_STALE_MS = 30_000;

function safeTimestampMs(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return parsed;
}

function pendingStartTimestampMs(value, fallbackNowMs = 0) {
  const directTimestamp = safeTimestampMs(value);
  if (directTimestamp > 0) {
    return directTimestamp;
  }
  if (value && typeof value === "object") {
    const fromObject = safeTimestampMs(value.started_at_ms);
    if (fromObject > 0) {
      return fromObject;
    }
  }
  if (value === true) {
    return safeTimestampMs(fallbackNowMs);
  }
  return 0;
}

export function isChatStarting(status, isRunning, isPendingStart) {
  if (Boolean(isRunning)) {
    return false;
  }
  const normalizedStatus = String(status || "").toLowerCase();
  if (normalizedStatus === "starting") {
    return true;
  }
  if (normalizedStatus === "failed" || normalizedStatus === "stopped" || normalizedStatus === "running") {
    return false;
  }
  return Boolean(isPendingStart);
}

export function findMatchingServerChatForPendingSession(session, serverChats, mappedServerIds) {
  if (!session || typeof session !== "object") {
    return null;
  }
  const projectId = String(session.project_id || "");
  if (!projectId) {
    return null;
  }
  const serverList = Array.isArray(serverChats) ? serverChats : [];
  const mappedServerIdSet = mappedServerIds instanceof Set ? mappedServerIds : new Set();
  const sessionRequestId = String(session.create_request_id || "").trim();
  const serverChatId = String(session.server_chat_id || "").trim();

  if (serverChatId) {
    for (const chat of serverList) {
      const chatId = String(chat?.id || "");
      if (!chatId || mappedServerIdSet.has(chatId)) {
        continue;
      }
      if (chatId !== serverChatId) {
        continue;
      }
      return chat;
    }
  }

  if (sessionRequestId) {
    for (const chat of serverList) {
      const chatId = String(chat?.id || "");
      if (!chatId || mappedServerIdSet.has(chatId)) {
        continue;
      }
      if (String(chat?.project_id || "") !== projectId) {
        continue;
      }
      const chatRequestId = String(chat?.create_request_id || "").trim();
      if (!chatRequestId || chatRequestId !== sessionRequestId) {
        continue;
      }
      return chat;
    }
  }
  return null;
}

export function reconcilePendingSessions(previousSessions, serverChatsById, nowMs = Date.now()) {
  const sessions = Array.isArray(previousSessions) ? previousSessions : [];
  const serverMap = serverChatsById instanceof Map ? serverChatsById : new Map();
  const currentTimeMs = safeTimestampMs(nowMs) || Date.now();

  const next = [];
  for (const session of sessions) {
    if (!session || typeof session !== "object") {
      continue;
    }
    const serverChatId = String(session.server_chat_id || "");
    if (!serverChatId) {
      next.push(session);
      continue;
    }

    const onServer = serverMap.has(serverChatId);
    const seenOnServer = Boolean(session.seen_on_server || onServer);
    if (seenOnServer && !onServer) {
      continue;
    }

    const serverChatIdSetAtMs = safeTimestampMs(session.server_chat_id_set_at_ms);
    const createdAtMs = safeTimestampMs(session.created_at_ms);
    const staleSinceMs = serverChatIdSetAtMs || createdAtMs;
    if (!onServer && !seenOnServer && staleSinceMs > 0 && currentTimeMs - staleSinceMs >= PENDING_SESSION_STALE_MS) {
      continue;
    }

    if (seenOnServer !== Boolean(session.seen_on_server)) {
      next.push({ ...session, seen_on_server: seenOnServer });
      continue;
    }

    next.push(session);
  }
  return next;
}

export function reconcilePendingProjectChatCreates(
  previousPendingProjectChatCreates,
  pendingSessions,
  serverChats,
  nowMs = Date.now()
) {
  const pendingCreates = previousPendingProjectChatCreates && typeof previousPendingProjectChatCreates === "object"
    ? previousPendingProjectChatCreates
    : {};
  const sessions = Array.isArray(pendingSessions) ? pendingSessions : [];
  const serverList = Array.isArray(serverChats) ? serverChats : [];
  const currentTimeMs = safeTimestampMs(nowMs) || Date.now();
  const next = {};

  for (const [projectId, startedAt] of Object.entries(pendingCreates)) {
    const normalizedProjectId = String(projectId || "").trim();
    if (!normalizedProjectId) {
      continue;
    }
    const startTimestampMs = safeTimestampMs(startedAt);
    if (startTimestampMs > 0 && currentTimeMs - startTimestampMs >= PENDING_SESSION_STALE_MS) {
      continue;
    }
    const projectSessions = sessions.filter(
      (session) => String(session?.project_id || "").trim() === normalizedProjectId
    );
    if (projectSessions.length === 0) {
      continue;
    }

    const hasUnmaterializedSession = projectSessions.some((session) => {
      const serverChatId = String(session?.server_chat_id || "").trim();
      if (serverChatId && serverList.some((chat) => String(chat?.id || "") === serverChatId)) {
        return false;
      }
      return !findMatchingServerChatForPendingSession(session, serverList, new Set());
    });
    if (hasUnmaterializedSession) {
      next[normalizedProjectId] = startTimestampMs || currentTimeMs;
    }
  }
  return next;
}

export function reconcilePendingChatStarts(previousPendingChatStarts, serverChatsById, nowMs = Date.now()) {
  const pending = previousPendingChatStarts && typeof previousPendingChatStarts === "object"
    ? previousPendingChatStarts
    : {};
  const serverMap = serverChatsById instanceof Map ? serverChatsById : new Map();
  const currentTimeMs = safeTimestampMs(nowMs) || Date.now();
  const next = {};
  for (const [chatId, pendingValue] of Object.entries(pending)) {
    const startTimestampMs = pendingStartTimestampMs(pendingValue, currentTimeMs);
    if (startTimestampMs <= 0) {
      continue;
    }

    const isStale = currentTimeMs - startTimestampMs >= PENDING_CHAT_START_STALE_MS;
    if (isStale) {
      continue;
    }

    const serverChat = serverMap.get(chatId);
    if (!serverChat) {
      next[chatId] = startTimestampMs;
      continue;
    }

    const normalizedStatus = String(serverChat.status || "").toLowerCase();
    if (normalizedStatus === "failed" || normalizedStatus === "stopped") {
      continue;
    }

    const isRunning = Boolean(serverChat.is_running);
    if (!isRunning && normalizedStatus === "starting") {
      next[chatId] = startTimestampMs;
    }
  }
  return next;
}
