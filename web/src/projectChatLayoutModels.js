export function buildProjectChatFlexModels(
  layoutsByProjectId,
  parseModelFromJson,
  onParseError = () => {},
  options = {}
) {
  if (typeof parseModelFromJson !== "function") {
    throw new TypeError("buildProjectChatFlexModels requires a parseModelFromJson function.");
  }
  if (typeof onParseError !== "function") {
    throw new TypeError("buildProjectChatFlexModels onParseError must be a function.");
  }
  const previousLayoutsByProjectId =
    options?.previousLayoutsByProjectId && typeof options.previousLayoutsByProjectId === "object"
      ? options.previousLayoutsByProjectId
      : {};
  const previousModelsByProjectId =
    options?.previousModelsByProjectId && typeof options.previousModelsByProjectId === "object"
      ? options.previousModelsByProjectId
      : {};
  const areLayoutsEqual = typeof options?.areLayoutsEqual === "function"
    ? options.areLayoutsEqual
    : (left, right) => {
      try {
        return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
      } catch {
        return false;
      }
    };
  const parsedModelsByProjectId = {};
  for (const [projectId, projectLayoutJson] of Object.entries(layoutsByProjectId || {})) {
    if (
      !projectLayoutJson ||
      typeof projectLayoutJson !== "object" ||
      !projectLayoutJson.layout ||
      typeof projectLayoutJson.layout !== "object"
    ) {
      continue;
    }
    const hasPreviousLayout = Object.prototype.hasOwnProperty.call(previousLayoutsByProjectId, projectId);
    const hasPreviousModel = Object.prototype.hasOwnProperty.call(previousModelsByProjectId, projectId);
    if (
      hasPreviousLayout &&
      hasPreviousModel &&
      areLayoutsEqual(previousLayoutsByProjectId[projectId], projectLayoutJson)
    ) {
      parsedModelsByProjectId[projectId] = previousModelsByProjectId[projectId];
      continue;
    }
    try {
      parsedModelsByProjectId[projectId] = parseModelFromJson(projectLayoutJson);
    } catch (err) {
      onParseError(projectId, err);
    }
  }
  return parsedModelsByProjectId;
}
