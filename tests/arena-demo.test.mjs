import assert from "node:assert/strict";
import test from "node:test";
import { initializeDemo } from "../js/app.js";
import { createFakeClock } from "./fake-clock.mjs";

function fakeElement(doc, { dataset = {}, html = "", text = "" } = {}) {
  const attributes = new Map();
  const listeners = new Map();
  let innerHTML = html;
  let textContent = text || html.replace(/<[^>]*>/g, "").trim();
  const element = {
    dataset: { ...dataset },
    disabled: false,
    hidden: false,
    addEventListener(type, callback) {
      listeners.set(type, callback);
    },
    setAttribute(name, value) {
      attributes.set(name, String(value));
    },
    removeAttribute(name) {
      attributes.delete(name);
    },
    focus() {
      doc.activeElement = element;
    },
    click() {
      if (!element.disabled && !element.hidden) {
        element.focus();
        listeners.get("click")?.({ target: element });
      }
    },
  };
  Object.defineProperties(element, {
    innerHTML: {
      get: () => innerHTML,
      set(value) {
        innerHTML = value;
        textContent = value.replace(/<[^>]*>/g, "").trim();
      },
    },
    textContent: {
      get: () => textContent,
      set(value) {
        textContent = value;
        innerHTML = value;
      },
    },
  });
  return element;
}

function createDemoFixture() {
  const doc = { activeElement: null };
  doc.body = fakeElement(doc);
  doc.activeElement = doc.body;
  const elements = new Map(
    Object.entries({
      "#arena-demo": fakeElement(doc),
      "#duel-button": fakeElement(doc, {
        html: '<span aria-hidden="true">▶</span> Start the duel',
      }),
      "#skip-button": fakeElement(doc, { text: "Skip" }),
      "#replay-button": fakeElement(doc, { text: "Play again" }),
      "#phase-title": fakeElement(doc),
      "#phase-copy": fakeElement(doc),
      "#mission-label": fakeElement(doc),
      "#demo-status": fakeElement(doc),
      "#duel-cue": fakeElement(doc),
      "#reward": fakeElement(doc),
    }),
  );
  const groups = {
    "[data-mission]": ["bug", "review", "memory"].map((mission) =>
      fakeElement(doc, { dataset: { mission } }),
    ),
    "[data-team-label]": ["a", "b"].map((team) =>
      fakeElement(doc, { dataset: { teamLabel: team } }),
    ),
    "[data-step]": ["compare", "validate", "complete"].map((phase) =>
      fakeElement(doc, { dataset: { step: phase } }),
    ),
  };
  doc.querySelector = (selector) => elements.get(selector) || null;
  doc.querySelectorAll = (selector) => groups[selector] || [];

  return { doc, elements, missionButtons: groups["[data-mission]"] };
}

function createMotionQuery(matches = false) {
  const listeners = new Set();
  return {
    query: {
      matches,
      addEventListener(type, listener) {
        if (type === "change") listeners.add(listener);
      },
    },
    change(nextMatches) {
      this.query.matches = nextMatches;
      for (const listener of listeners) listener({ matches: nextMatches });
    },
  };
}

function initializeFixture(fixture, clock, motion = createMotionQuery()) {
  initializeDemo(fixture.doc, {
    motionQuery: motion.query,
    scheduleOptions: {
      setTimeout: clock.setTimeout,
      clearTimeout: clock.clearTimeout,
    },
  });
  return motion;
}

test("skip unlocks the reward and replay resets the duel for another run", () => {
  const fixture = createDemoFixture();
  const clock = createFakeClock();
  initializeFixture(fixture, clock);
  const arena = fixture.elements.get("#arena-demo");
  const duelButton = fixture.elements.get("#duel-button");
  const skipButton = fixture.elements.get("#skip-button");
  const replayButton = fixture.elements.get("#replay-button");
  const reward = fixture.elements.get("#reward");

  duelButton.click();
  assert.equal(arena.dataset.phase, "compare");
  assert.equal(arena.dataset.beat, "ready");
  assert.equal(skipButton.hidden, false);
  assert.equal(skipButton.disabled, false);
  assert.equal(fixture.doc.activeElement, skipButton);

  skipButton.click();
  assert.equal(arena.dataset.phase, "complete");
  assert.equal(arena.dataset.beat, "reward");
  assert.equal(reward.hidden, false);
  assert.equal(replayButton.hidden, false);
  assert.equal(
    fixture.elements.get("#demo-status").textContent,
    "Verified. Playbook unlocked. Replay to watch again.",
  );
  assert.equal(fixture.doc.activeElement, replayButton);
  assert.equal(clock.pendingCount, 0);

  replayButton.click();
  assert.equal(arena.dataset.phase, "idle");
  assert.equal(arena.dataset.beat, "ready");
  assert.equal(reward.hidden, true);
  assert.equal(skipButton.hidden, true);
  assert.equal(duelButton.disabled, false);
  assert.match(duelButton.textContent, /Start the duel/);
  assert.equal(fixture.doc.activeElement, duelButton);

  duelButton.click();
  assert.equal(arena.dataset.phase, "compare");
  assert.equal(clock.pendingCount, 1);
  skipButton.click();
  clock.fireCleared();
  assert.equal(arena.dataset.phase, "complete");
  assert.equal(arena.dataset.beat, "reward");
});

test("a motion preference change finishes safely and later timer callbacks stay inert", () => {
  const fixture = createDemoFixture();
  const clock = createFakeClock();
  const motion = initializeFixture(fixture, clock);
  const arena = fixture.elements.get("#arena-demo");

  fixture.elements.get("#duel-button").click();
  clock.tick(500);
  assert.equal(arena.dataset.beat, "blue-attack");

  motion.change(true);
  assert.equal(arena.dataset.reducedMotion, "true");
  assert.equal(arena.dataset.phase, "complete");
  assert.equal(arena.dataset.beat, "reward");
  assert.equal(clock.pendingCount, 0);
  clock.fireCleared();
  assert.equal(arena.dataset.phase, "complete");
  assert.equal(arena.dataset.beat, "reward");
});

test("completion does not move focus after the user leaves the duel controls", () => {
  const fixture = createDemoFixture();
  const clock = createFakeClock();
  initializeFixture(fixture, clock);
  const elsewhere = fakeElement(fixture.doc);

  fixture.elements.get("#duel-button").click();
  elsewhere.focus();
  clock.tick(5600);

  assert.equal(fixture.elements.get("#arena-demo").dataset.phase, "complete");
  assert.equal(fixture.doc.activeElement, elsewhere);
});

test("enabling motion after a reduced-motion reward does not replay its celebration", () => {
  const fixture = createDemoFixture();
  const clock = createFakeClock();
  const motion = initializeFixture(fixture, clock, createMotionQuery(true));
  const arena = fixture.elements.get("#arena-demo");

  fixture.elements.get("#duel-button").click();
  clock.tick(700);
  assert.equal(arena.dataset.phase, "complete");
  assert.equal(arena.dataset.rewardMotion, "false");

  motion.change(false);
  assert.equal(arena.dataset.reducedMotion, "false");
  assert.equal(arena.dataset.rewardMotion, "false");
  assert.equal(clock.pendingCount, 0);

  fixture.elements.get("#replay-button").click();
  fixture.elements.get("#duel-button").click();
  assert.equal(arena.dataset.rewardMotion, "true");
});
