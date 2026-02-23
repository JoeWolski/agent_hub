export const CHAT_LAYOUT_ENGINE_CLASSIC = "classic";
export const CHAT_LAYOUT_ENGINE_FLEXLAYOUT = "flexlayout";
export const DEFAULT_CHAT_LAYOUT_ENGINE = CHAT_LAYOUT_ENGINE_FLEXLAYOUT;

const CHAT_LAYOUT_ENGINE_DEFINITIONS = Object.freeze([
  Object.freeze({
    value: CHAT_LAYOUT_ENGINE_CLASSIC,
    label: "Classic"
  }),
  Object.freeze({
    value: CHAT_LAYOUT_ENGINE_FLEXLAYOUT,
    label: "FlexLayout"
  })
]);

const CHAT_LAYOUT_ENGINE_VALUES = new Set(
  CHAT_LAYOUT_ENGINE_DEFINITIONS.map((definition) => definition.value)
);

export function normalizeChatLayoutEngine(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (CHAT_LAYOUT_ENGINE_VALUES.has(normalized)) {
    return normalized;
  }
  return DEFAULT_CHAT_LAYOUT_ENGINE;
}

export function chatLayoutEngineOptions() {
  return CHAT_LAYOUT_ENGINE_DEFINITIONS;
}
