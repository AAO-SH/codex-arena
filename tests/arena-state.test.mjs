import assert from "node:assert/strict";
import test from "node:test";
import {
  createInitialState,
  MISSION_LABELS,
  reduceArenaState,
} from "../js/arena-state.js";

test("mission labels are clear and in English", () => {
  assert.deepEqual(MISSION_LABELS, {
    bug: "Fix a bug",
    review: "Review code",
    memory: "Organize knowledge",
  });
});

test("mission selection updates the idle state", () => {
  const initial = createInitialState();
  const selected = reduceArenaState(initial, {
    type: "select-mission",
    mission: "review",
  });

  assert.deepEqual(selected, { mission: "review", phase: "idle" });
  assert.deepEqual(initial, { mission: "bug", phase: "idle" });
});

test("mission selection is ignored while the demo is running", () => {
  const running = reduceArenaState(createInitialState(), { type: "start" });

  assert.deepEqual(
    reduceArenaState(running, { type: "select-mission", mission: "memory" }),
    running,
  );
});

test("the demo advances through compare, validate, and complete", () => {
  const compare = reduceArenaState(createInitialState(), { type: "start" });
  const validate = reduceArenaState(compare, { type: "advance" });
  const complete = reduceArenaState(validate, { type: "advance" });

  assert.deepEqual(compare, { mission: "bug", phase: "compare" });
  assert.deepEqual(validate, { mission: "bug", phase: "validate" });
  assert.deepEqual(complete, { mission: "bug", phase: "complete" });
  assert.deepEqual(reduceArenaState(complete, { type: "advance" }), complete);
});

test("replay resets the phase and keeps the selected mission", () => {
  const complete = {
    mission: "review",
    phase: "complete",
  };

  assert.deepEqual(reduceArenaState(complete, { type: "replay" }), {
    mission: "review",
    phase: "idle",
  });
});

test("changing the mission after completion resets to idle", () => {
  const complete = { mission: "bug", phase: "complete" };

  assert.deepEqual(
    reduceArenaState(complete, { type: "select-mission", mission: "review" }),
    { mission: "review", phase: "idle" },
  );
  assert.deepEqual(
    reduceArenaState(complete, { type: "select-mission", mission: "bug" }),
    complete,
  );
});

test("invalid missions, phases, and actions are rejected", () => {
  assert.throws(() => createInitialState("unknown"), RangeError);
  assert.throws(
    () =>
      reduceArenaState({ mission: "bug", phase: "broken" }, { type: "start" }),
    RangeError,
  );
  assert.throws(
    () => reduceArenaState(createInitialState(), { type: "unknown" }),
    RangeError,
  );
});
