import test from "node:test";
import assert from "node:assert/strict";
import {
  findMatchingServerChatForPendingSession,
  isChatStarting,
  reconcilePendingChatStarts,
  reconcilePendingProjectChatCreates
} from "./chatPendingState.js";

test("reconcilePendingProjectChatCreates keeps project create pending while no server chat exists", () => {
  const next = reconcilePendingProjectChatCreates(
    { "project-1": 1000 },
    [
      {
        ui_id: "pending-1",
        project_id: "project-1",
        create_request_id: "chat-create-pending-1",
        server_chat_id: "",
        created_at_ms: 1000
      }
    ],
    [],
    1500
  );

  assert.deepEqual(next, { "project-1": 1000 });
});

test("reconcilePendingProjectChatCreates clears project create once request-id matched chat exists", () => {
  const next = reconcilePendingProjectChatCreates(
    { "project-1": 1000 },
    [
      {
        ui_id: "pending-1",
        project_id: "project-1",
        create_request_id: "chat-create-pending-1",
        server_chat_id: "",
        created_at_ms: 1000
      }
    ],
    [
      {
        id: "chat-1",
        project_id: "project-1",
        create_request_id: "chat-create-pending-1",
        status: "failed",
        is_running: false
      }
    ],
    1500
  );

  assert.deepEqual(next, {});
});

test("reconcilePendingProjectChatCreates clears project create once server chat id exists on server", () => {
  const next = reconcilePendingProjectChatCreates(
    { "project-1": 1000 },
    [
      {
        ui_id: "pending-1",
        project_id: "project-1",
        create_request_id: "chat-create-pending-1",
        server_chat_id: "chat-1",
        created_at_ms: 1000
      }
    ],
    [
      {
        id: "chat-1",
        project_id: "project-1",
        create_request_id: "chat-create-pending-1",
        status: "failed",
        is_running: false
      }
    ],
    1500
  );

  assert.deepEqual(next, {});
});

test("findMatchingServerChatForPendingSession does not fall back to same-project startup candidates", () => {
  const matched = findMatchingServerChatForPendingSession(
    {
      ui_id: "pending-1",
      project_id: "project-1",
      create_request_id: "req-1",
      known_server_chat_ids: []
    },
    [
      {
        id: "chat-starting",
        project_id: "project-1",
        create_request_id: "other-req",
        status: "starting",
        is_running: false
      }
    ],
    new Set()
  );

  assert.equal(matched, null);
});

test("reconcilePendingChatStarts drops terminal states immediately", () => {
  const next = reconcilePendingChatStarts(
    {
      "chat-starting": 1000,
      "chat-stopped": 1000,
      "chat-failed": 1000
    },
    new Map([
      ["chat-starting", { status: "starting", is_running: false }],
      ["chat-stopped", { status: "stopped", is_running: false }],
      ["chat-failed", { status: "failed", is_running: false }]
    ]),
    2000
  );

  assert.deepEqual(next, { "chat-starting": 1000 });
});

test("isChatStarting does not treat stopped chats as starting from stale pending state", () => {
  assert.equal(isChatStarting("stopped", false, true), false);
  assert.equal(isChatStarting("failed", false, true), false);
  assert.equal(isChatStarting("starting", false, false), true);
});
