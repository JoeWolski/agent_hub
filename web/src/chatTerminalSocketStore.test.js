import test from "node:test";
import assert from "node:assert/strict";
import { createChatTerminalSocketStore } from "./chatTerminalSocketStore.js";

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.closeCalls = 0;
    this.listeners = {
      open: new Set(),
      message: new Set(),
      close: new Set(),
      error: new Set()
    };
  }

  addEventListener(type, callback) {
    const bucket = this.listeners[type];
    if (!bucket) {
      return;
    }
    bucket.add(callback);
  }

  removeEventListener(type, callback) {
    const bucket = this.listeners[type];
    if (!bucket) {
      return;
    }
    bucket.delete(callback);
  }

  emit(type, payload = {}) {
    const bucket = this.listeners[type];
    if (!bucket) {
      return;
    }
    for (const callback of Array.from(bucket)) {
      callback(payload);
    }
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.emit("open");
  }

  receive(data) {
    this.emit("message", { data });
  }

  fail() {
    this.emit("error");
  }

  serverClose() {
    if (this.readyState === FakeWebSocket.CLOSED) {
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close");
  }

  close() {
    this.closeCalls += 1;
    if (this.readyState === FakeWebSocket.CLOSED) {
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close");
  }

  send(payload) {
    this.sent.push(String(payload));
  }
}

function createFakeTimers() {
  let nextTimerId = 1;
  const pending = new Map();
  return {
    setTimeout(callback) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      pending.set(timerId, callback);
      return timerId;
    },
    clearTimeout(timerId) {
      pending.delete(timerId);
    },
    runNext() {
      const next = pending.entries().next();
      if (next.done) {
        return false;
      }
      const [timerId, callback] = next.value;
      pending.delete(timerId);
      callback();
      return true;
    },
    pendingCount() {
      return pending.size;
    }
  };
}

test("keeps chat terminal socket alive across subscriber unmount/remount", () => {
  const timers = createFakeTimers();
  const sockets = [];
  const store = createChatTerminalSocketStore({
    makeSocketUrl: (chatId) => `ws://example.test/${chatId}`,
    createWebSocket: (url) => {
      const socket = new FakeWebSocket(url);
      sockets.push(socket);
      return socket;
    },
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
    maxBufferedChars: 4_096
  });

  store.setRunning("chat-1", true);
  assert.equal(sockets.length, 1);
  const firstSocket = sockets[0];
  const firstStatuses = [];
  const firstData = [];
  const firstBacklogs = [];
  const unsubscribeFirst = store.subscribe("chat-1", {
    onStatus: (status) => firstStatuses.push(status),
    onBacklog: (text) => firstBacklogs.push(text),
    onData: (chunk) => firstData.push(chunk)
  });

  firstSocket.open();
  firstSocket.receive("hello\n");
  unsubscribeFirst();
  firstSocket.receive("world\n");

  const secondStatuses = [];
  const secondBacklogs = [];
  const secondData = [];
  const unsubscribeSecond = store.subscribe("chat-1", {
    onStatus: (status) => secondStatuses.push(status),
    onBacklog: (text) => secondBacklogs.push(text),
    onData: (chunk) => secondData.push(chunk)
  });

  assert.ok(firstStatuses.includes("connected"));
  assert.deepEqual(firstBacklogs, []);
  assert.deepEqual(firstData, ["hello\n"]);
  assert.deepEqual(secondStatuses, ["connected"]);
  assert.deepEqual(secondBacklogs, ["hello\nworld\n"]);
  assert.deepEqual(secondData, []);
  assert.equal(sockets.length, 1);
  assert.equal(timers.pendingCount(), 0);

  unsubscribeSecond();
});

test("reconnects automatically after server-side websocket close while running", () => {
  const timers = createFakeTimers();
  const sockets = [];
  const store = createChatTerminalSocketStore({
    makeSocketUrl: (chatId) => `ws://example.test/${chatId}`,
    createWebSocket: (url) => {
      const socket = new FakeWebSocket(url);
      sockets.push(socket);
      return socket;
    },
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout
  });

  const statuses = [];
  const unsubscribe = store.subscribe("chat-1", {
    onStatus: (status) => statuses.push(status)
  });

  store.setRunning("chat-1", true);
  assert.equal(sockets.length, 1);
  const firstSocket = sockets[0];
  firstSocket.open();
  firstSocket.serverClose();

  assert.equal(statuses.at(-1), "closed");
  assert.equal(timers.pendingCount(), 1);
  assert.equal(sockets.length, 1);
  assert.equal(timers.runNext(), true);
  assert.equal(sockets.length, 2);

  const secondSocket = sockets[1];
  secondSocket.open();
  assert.equal(statuses.at(-1), "connected");

  unsubscribe();
});

test("syncRunningStates closes sockets for chats that are no longer running", () => {
  const timers = createFakeTimers();
  const sockets = [];
  const store = createChatTerminalSocketStore({
    makeSocketUrl: (chatId) => `ws://example.test/${chatId}`,
    createWebSocket: (url) => {
      const socket = new FakeWebSocket(url);
      sockets.push(socket);
      return socket;
    },
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout
  });

  store.setRunning("chat-1", true);
  assert.equal(sockets.length, 1);
  const socket = sockets[0];
  socket.open();
  const sentResize = store.sendResize("chat-1", 120, 40, { force: true });
  assert.equal(sentResize, true);
  assert.equal(socket.sent.length, 1);

  store.syncRunningStates([]);
  assert.equal(socket.closeCalls, 1);
  assert.equal(store.sendInput("chat-1", "pwd"), false);
  assert.equal(timers.pendingCount(), 0);
  assert.deepEqual(store.debugSnapshot(), []);
});
