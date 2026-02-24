import test from "node:test";
import assert from "node:assert/strict";
import { buildProjectChatFlexModels } from "./projectChatLayoutModels.js";

test("buildProjectChatFlexModels parses each valid project layout exactly once", () => {
  const parseCalls = [];
  const layoutOne = { layout: { type: "row" } };
  const layoutTwo = { layout: { type: "tabset" } };
  const parsed = buildProjectChatFlexModels(
    { alpha: layoutOne, beta: layoutTwo },
    (layoutJson) => {
      parseCalls.push(layoutJson);
      return { parsedLayout: layoutJson.layout.type };
    }
  );

  assert.deepEqual(parseCalls, [layoutOne, layoutTwo]);
  assert.deepEqual(parsed, {
    alpha: { parsedLayout: "row" },
    beta: { parsedLayout: "tabset" }
  });
});

test("buildProjectChatFlexModels ignores projects with invalid layout payloads", () => {
  let parseCallCount = 0;
  const parsed = buildProjectChatFlexModels(
    {
      empty: null,
      missingLayout: {},
      invalidLayout: { layout: "tabset" },
      valid: { layout: { type: "tabset" } }
    },
    (layoutJson) => {
      parseCallCount += 1;
      return layoutJson.layout.type;
    }
  );

  assert.equal(parseCallCount, 1);
  assert.deepEqual(parsed, { valid: "tabset" });
});

test("buildProjectChatFlexModels reports parse failures and continues", () => {
  const parseErrors = [];
  const parsed = buildProjectChatFlexModels(
    {
      bad: { layout: { type: "invalid" } },
      good: { layout: { type: "tabset" } }
    },
    (layoutJson) => {
      if (layoutJson.layout.type === "invalid") {
        throw new Error("cannot parse invalid model");
      }
      return { ok: true };
    },
    (projectId, err) => {
      parseErrors.push({ projectId, message: err.message });
    }
  );

  assert.deepEqual(parseErrors, [{ projectId: "bad", message: "cannot parse invalid model" }]);
  assert.deepEqual(parsed, { good: { ok: true } });
});

test("buildProjectChatFlexModels reuses previous models when layouts are unchanged", () => {
  const previousModel = { from: "cached" };
  let parseCallCount = 0;
  const parsed = buildProjectChatFlexModels(
    {
      alpha: { layout: { type: "row", children: [] } }
    },
    () => {
      parseCallCount += 1;
      return { from: "parsed" };
    },
    () => {},
    {
      previousLayoutsByProjectId: {
        alpha: { layout: { type: "row", children: [] } }
      },
      previousModelsByProjectId: {
        alpha: previousModel
      }
    }
  );

  assert.equal(parseCallCount, 0);
  assert.equal(parsed.alpha, previousModel);
});

test("buildProjectChatFlexModels reparses when project layout changes", () => {
  const parsed = buildProjectChatFlexModels(
    {
      alpha: { layout: { type: "row", children: [{ type: "tabset" }] } }
    },
    () => ({ from: "parsed" }),
    () => {},
    {
      previousLayoutsByProjectId: {
        alpha: { layout: { type: "row", children: [] } }
      },
      previousModelsByProjectId: {
        alpha: { from: "cached" }
      }
    }
  );

  assert.deepEqual(parsed, { alpha: { from: "parsed" } });
});
