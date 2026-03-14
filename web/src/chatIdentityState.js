import { rekeyProjectChatPaneTabIds } from "./flexLayoutState.js";

function objectMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value;
}

function moveKeyedUiState(mapValue, uiId, serverChatId, merger = null) {
  const source = objectMap(mapValue);
  const next = { ...source };
  const pendingValue = next[uiId];
  const existingServerValue = next[serverChatId];
  const resolvedServerValue = merger
    ? merger(existingServerValue, pendingValue)
    : (existingServerValue || pendingValue);
  if (resolvedServerValue !== undefined) {
    next[serverChatId] = resolvedServerValue;
  }
  delete next[uiId];
  return next;
}

function moveChatStaticLogs(mapValue, uiId, serverChatId) {
  return moveKeyedUiState(mapValue, uiId, serverChatId, (existingServerValue, pendingValue) => {
    if (String(existingServerValue || "").trim()) {
      return existingServerValue;
    }
    return pendingValue;
  });
}

export function rekeyChatUiIdentityState(prev, uiId, serverChatId) {
  const normalizedUiId = String(uiId || "").trim();
  const normalizedServerChatId = String(serverChatId || "").trim();
  if (!normalizedUiId || !normalizedServerChatId || normalizedUiId === normalizedServerChatId) {
    return prev;
  }

  const sourcePendingSessions = Array.isArray(prev?.pendingSessions) ? prev.pendingSessions : [];
  const matchedSession = sourcePendingSessions.find(
    (session) => String(session?.ui_id || "").trim() === normalizedUiId
  );
  if (!matchedSession) {
    return prev;
  }
  const matchedProjectId = String(matchedSession?.project_id || "").trim();
  const matchedRequestId = String(matchedSession?.create_request_id || "").trim();
  const pendingSessions = sourcePendingSessions.filter((session) => {
    const sessionUiId = String(session?.ui_id || "").trim();
    if (sessionUiId === normalizedUiId) {
      return false;
    }
    const sessionServerChatId = String(session?.server_chat_id || "").trim();
    if (sessionServerChatId && sessionServerChatId === normalizedServerChatId) {
      return false;
    }
    const sessionProjectId = String(session?.project_id || "").trim();
    const sessionRequestId = String(session?.create_request_id || "").trim();
    return !(matchedProjectId && matchedRequestId && sessionProjectId === matchedProjectId && sessionRequestId === matchedRequestId);
  });

  const chatFlexProjectLayoutsByProjectId = Object.fromEntries(
    Object.entries(objectMap(prev?.chatFlexProjectLayoutsByProjectId)).map(([projectId, layoutJson]) => [
      projectId,
      projectId === matchedProjectId
        ? rekeyProjectChatPaneTabIds(layoutJson, normalizedUiId, normalizedServerChatId)
        : layoutJson
    ])
  );

  return {
    pendingSessions,
    openChats: moveKeyedUiState(prev?.openChats, normalizedUiId, normalizedServerChatId),
    openChatDetails: moveKeyedUiState(prev?.openChatDetails, normalizedUiId, normalizedServerChatId),
    openChatLogs: moveKeyedUiState(prev?.openChatLogs, normalizedUiId, normalizedServerChatId),
    pendingChatLogLoads: moveKeyedUiState(prev?.pendingChatLogLoads, normalizedUiId, normalizedServerChatId),
    chatStaticLogs: moveChatStaticLogs(prev?.chatStaticLogs, normalizedUiId, normalizedServerChatId),
    showArtifactThumbnailsByChat: moveKeyedUiState(
      prev?.showArtifactThumbnailsByChat,
      normalizedUiId,
      normalizedServerChatId
    ),
    collapsedTerminalsByChat: moveKeyedUiState(prev?.collapsedTerminalsByChat, normalizedUiId, normalizedServerChatId),
    fullscreenChatId: String(prev?.fullscreenChatId || "") === normalizedUiId
      ? normalizedServerChatId
      : String(prev?.fullscreenChatId || ""),
    artifactPreview: prev?.artifactPreview && String(prev.artifactPreview.chatId || "") === normalizedUiId
      ? { ...prev.artifactPreview, chatId: normalizedServerChatId }
      : (prev?.artifactPreview ?? null),
    chatFlexProjectLayoutsByProjectId
  };
}
