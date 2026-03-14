import test from "node:test";
import assert from "node:assert/strict";
import { rekeyChatUiIdentityState } from "./chatIdentityState.js";

test("rekeyChatUiIdentityState promotes pending UI state to authoritative chat id", () => {
  const next = rekeyChatUiIdentityState(
    {
      pendingSessions: [
        { ui_id: "pending-1", project_id: "project-1", create_request_id: "req-1" }
      ],
      openChats: { "pending-1": true },
      openChatDetails: { "pending-1": false },
      openChatLogs: { "pending-1": true },
      pendingChatLogLoads: { "pending-1": true },
      chatStaticLogs: { "pending-1": "pending log" },
      showArtifactThumbnailsByChat: { "pending-1": true },
      collapsedTerminalsByChat: { "pending-1": true },
      fullscreenChatId: "pending-1",
      artifactPreview: { chatId: "pending-1", artifactId: "artifact-1" },
      chatFlexProjectLayoutsByProjectId: {
        "project-1": {
          global: {},
          borders: [],
          layout: {
            type: "row",
            children: [
              {
                type: "tabset",
                selected: 0,
                children: [
                  {
                    type: "tab",
                    id: "chat-pending-1",
                    name: "Pending",
                    component: "project-chat-pane",
                    config: { chat_id: "pending-1" }
                  }
                ]
              }
            ]
          }
        }
      }
    },
    "pending-1",
    "chat-1"
  );

  assert.deepEqual(next.pendingSessions, []);
  assert.equal(next.openChats["chat-1"], true);
  assert.equal(next.openChats["pending-1"], undefined);
  assert.equal(next.chatStaticLogs["chat-1"], "pending log");
  assert.equal(next.fullscreenChatId, "chat-1");
  assert.equal(next.artifactPreview.chatId, "chat-1");
  const projectLayout = next.chatFlexProjectLayoutsByProjectId["project-1"];
  assert.equal(projectLayout.layout.children[0].children[0].id, "chat-chat-1");
  assert.equal(projectLayout.layout.children[0].children[0].config.chat_id, "chat-1");
});

test("rekeyChatUiIdentityState only rewrites the matching project layout", () => {
  const next = rekeyChatUiIdentityState(
    {
      pendingSessions: [
        { ui_id: "pending-1", project_id: "project-1", create_request_id: "req-1" }
      ],
      openChats: {},
      openChatDetails: {},
      openChatLogs: {},
      pendingChatLogLoads: {},
      chatStaticLogs: {},
      showArtifactThumbnailsByChat: {},
      collapsedTerminalsByChat: {},
      fullscreenChatId: "",
      artifactPreview: null,
      chatFlexProjectLayoutsByProjectId: {
        "project-1": {
          global: {},
          borders: [],
          layout: {
            type: "row",
            children: [
              {
                type: "tabset",
                selected: 0,
                children: [
                  {
                    type: "tab",
                    id: "chat-pending-1",
                    name: "Pending",
                    component: "project-chat-pane",
                    config: { chat_id: "pending-1" }
                  }
                ]
              }
            ]
          }
        },
        "project-2": {
          global: {},
          borders: [],
          layout: {
            type: "row",
            children: [
              {
                type: "tabset",
                selected: 0,
                children: [
                  {
                    type: "tab",
                    id: "chat-pending-1",
                    name: "Pending",
                    component: "project-chat-pane",
                    config: { chat_id: "pending-1" }
                  }
                ]
              }
            ]
          }
        }
      }
    },
    "pending-1",
    "chat-1"
  );

  assert.equal(
    next.chatFlexProjectLayoutsByProjectId["project-1"].layout.children[0].children[0].config.chat_id,
    "chat-1"
  );
  assert.equal(
    next.chatFlexProjectLayoutsByProjectId["project-2"].layout.children[0].children[0].config.chat_id,
    "pending-1"
  );
});

test("rekeyChatUiIdentityState preserves authoritative values and is idempotent", () => {
  const initial = {
    pendingSessions: [{ ui_id: "pending-1", project_id: "project-1" }],
    openChats: { "pending-1": true, "chat-1": false },
    openChatDetails: {},
    openChatLogs: {},
    pendingChatLogLoads: {},
    chatStaticLogs: { "pending-1": "pending", "chat-1": "server" },
    showArtifactThumbnailsByChat: {},
    collapsedTerminalsByChat: {},
    fullscreenChatId: "",
    artifactPreview: null,
    chatFlexProjectLayoutsByProjectId: {}
  };

  const once = rekeyChatUiIdentityState(initial, "pending-1", "chat-1");
  const twice = rekeyChatUiIdentityState(once, "pending-1", "chat-1");

  assert.equal(once.openChats["chat-1"], true);
  assert.equal(once.chatStaticLogs["chat-1"], "server");
  assert.deepEqual(twice, once);
});

test("rekeyChatUiIdentityState drops duplicate pending sessions for the same create request", () => {
  const next = rekeyChatUiIdentityState(
    {
      pendingSessions: [
        { ui_id: "pending-1", project_id: "project-1", create_request_id: "req-1" },
        { ui_id: "pending-2", project_id: "project-1", create_request_id: "req-1" },
        { ui_id: "pending-3", project_id: "project-2", create_request_id: "req-1" }
      ],
      openChats: { "pending-1": true, "pending-2": false, "pending-3": true },
      openChatDetails: {},
      openChatLogs: {},
      pendingChatLogLoads: {},
      chatStaticLogs: {},
      showArtifactThumbnailsByChat: {},
      collapsedTerminalsByChat: {},
      fullscreenChatId: "",
      artifactPreview: null,
      chatFlexProjectLayoutsByProjectId: {}
    },
    "pending-1",
    "chat-1"
  );

  assert.deepEqual(next.pendingSessions, [
    { ui_id: "pending-3", project_id: "project-2", create_request_id: "req-1" }
  ]);
});
