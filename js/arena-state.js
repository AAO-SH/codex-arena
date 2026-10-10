export const MISSION_LABELS = Object.freeze({
  bug: "Fix a bug",
  review: "Review code",
  memory: "Organize knowledge",
});

export const ARENA_PHASES = Object.freeze([
  "idle",
  "compare",
  "validate",
  "complete",
]);

const ACTIVE_PHASES = new Set(["compare", "validate"]);

export function createInitialState(mission = "bug") {
  assertMission(mission);
  return { mission, phase: "idle" };
}

export function reduceArenaState(state, action) {
  assertState(state);
  assertAction(action);

  switch (action.type) {
    case "select-mission":
      assertMission(action.mission);
      if (ACTIVE_PHASES.has(state.phase)) return state;
      if (state.phase === "complete" && state.mission !== action.mission) {
        return { mission: action.mission, phase: "idle" };
      }
      return { ...state, mission: action.mission };

    case "start":
      return state.phase === "idle" ? { ...state, phase: "compare" } : state;

    case "advance":
      if (state.phase === "compare") {
        return { ...state, phase: "validate" };
      }
      if (state.phase === "validate") {
        return { ...state, phase: "complete" };
      }
      return state;

    case "replay":
      return { mission: state.mission, phase: "idle" };

    default:
      throw new RangeError(`Unknown arena action: ${String(action.type)}`);
  }
}

function assertState(state) {
  if (state === null || typeof state !== "object") {
    throw new TypeError("Arena state must be an object");
  }

  assertMission(state.mission);
  if (!ARENA_PHASES.includes(state.phase)) {
    throw new RangeError(`Unknown arena phase: ${String(state.phase)}`);
  }
}

function assertAction(action) {
  if (
    action === null ||
    typeof action !== "object" ||
    typeof action.type !== "string"
  ) {
    throw new TypeError("Arena action must have a string type");
  }
}

function assertMission(mission) {
  if (!Object.hasOwn(MISSION_LABELS, mission)) {
    throw new RangeError(`Unknown arena mission: ${String(mission)}`);
  }
}
