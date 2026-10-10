import assert from "node:assert/strict";
import test from "node:test";
import {
  createDuelTimeline,
  scheduleDuelTimeline,
} from "../js/duel-timeline.js";
import { createFakeClock } from "./fake-clock.mjs";

function captureTimeline(clock, options = {}) {
  const events = [];
  const handle = scheduleDuelTimeline({
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    onPhase: (phase) => events.push(["phase", phase]),
    onBeat: (beat) => events.push(["beat", beat]),
    onComplete: () => events.push(["complete"]),
    ...options,
  });
  return { events, handle };
}

test("the normal duel runs the seven attack and defense beats before verification", () => {
  const clock = createFakeClock();
  const { events } = captureTimeline(clock);

  assert.deepEqual(events, [
    ["phase", "compare"],
    ["beat", "ready"],
  ]);
  clock.tick(500);
  assert.deepEqual(events.slice(-1), [["beat", "blue-attack"]]);
  clock.tick(700 + 550 + 700 + 550 + 850 + 550);
  assert.deepEqual(events.slice(-2), [
    ["phase", "validate"],
    ["beat", "verify"],
  ]);
  clock.tick(1199);
  assert.notEqual(events.at(-1)[1], "complete");
  clock.tick(1);

  assert.deepEqual(events.slice(-3), [
    ["phase", "complete"],
    ["beat", "reward"],
    ["complete"],
  ]);
  assert.equal(clock.pendingCount, 0);
});

test("finishing early clears timers and ignores callbacks that arrive late", () => {
  const clock = createFakeClock();
  const { events, handle } = captureTimeline(clock);
  clock.tick(500);

  assert.equal(handle.finish(), true);
  assert.deepEqual(events.slice(-3), [
    ["phase", "complete"],
    ["beat", "reward"],
    ["complete"],
  ]);
  assert.equal(clock.pendingCount, 0);
  clock.fireCleared();
  assert.equal(handle.finish(), false);
  assert.deepEqual(events.slice(-3), [
    ["phase", "complete"],
    ["beat", "reward"],
    ["complete"],
  ]);
});

test("canceling a run before replay prevents its stale callback from changing the new run", () => {
  const clock = createFakeClock();
  const events = [];
  const first = scheduleDuelTimeline({
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    onBeat: (beat) => events.push(`first:${beat}`),
  });
  clock.tick(500);
  assert.equal(first.cancel(), true);

  const second = scheduleDuelTimeline({
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    onBeat: (beat) => events.push(`second:${beat}`),
  });
  const beforeLateCallback = [...events];
  clock.fireCleared();
  assert.deepEqual(events, beforeLateCallback);
  clock.tick(500);
  assert.equal(events.at(-1), "second:blue-attack");

  second.cancel();
});

test("reduced motion keeps only ready and verify beats with short durations", () => {
  const timeline = createDuelTimeline({ reducedMotion: true });
  assert.deepEqual(
    timeline.map(({ beat, phase }) => [phase, beat]),
    [
      ["compare", "ready"],
      ["validate", "verify"],
      ["complete", "reward"],
    ],
  );
  assert.ok(
    timeline
      .filter((step) => step.duration)
      .every((step) => step.duration <= 500),
  );

  const clock = createFakeClock();
  const { events } = captureTimeline(clock, { reducedMotion: true });
  clock.tick(350);
  assert.deepEqual(events.slice(-2), [
    ["phase", "validate"],
    ["beat", "verify"],
  ]);
  clock.tick(350);
  assert.deepEqual(events.slice(-3), [
    ["phase", "complete"],
    ["beat", "reward"],
    ["complete"],
  ]);
});

test("the normal sequence totals 4.4 seconds before verification", () => {
  const compareDuration = createDuelTimeline()
    .filter((step) => step.phase === "compare")
    .reduce((total, step) => total + step.duration, 0);

  assert.equal(compareDuration, 4400);
});
