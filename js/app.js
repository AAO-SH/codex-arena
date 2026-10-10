import {
  createInitialState,
  MISSION_LABELS,
  reduceArenaState,
} from "./arena-state.js";
import { scheduleDuelTimeline } from "./duel-timeline.js";

const MISSION_TEAMS = Object.freeze({
  bug: Object.freeze({ a: "Test-first", b: "Trace-first" }),
  review: Object.freeze({ a: "Checklist-first", b: "Risk-first" }),
  memory: Object.freeze({ a: "Tags", b: "Linked notes" }),
});

const PHASE_CONTENT = Object.freeze({
  idle: {
    title: "Ready for the arena",
    copy: "Choose a mission and start the demo.",
    status: "Demo ready.",
  },
  compare: {
    title: "Strategies in the arena",
    copy: "",
    status: "Duel started. Watch both strategies compete.",
  },
  validate: {
    title: "Time to verify",
    copy: "Demo: Test the method against a baseline.",
    status: "Duel complete. Verifying the result.",
  },
  complete: {
    title: "Playbook unlocked",
    copy: "Demo: reusable scripts and instructions, ready to use.",
    status: "Verified. Playbook unlocked. Replay to watch again.",
  },
});

const DUEL_CUES = Object.freeze({
  ready: "Ready!",
  "blue-attack": "Attack!",
  "red-block": "Blocked!",
  "red-attack": "Attack!",
  "blue-block": "Blocked!",
  clash: "Clash!",
  recover: "Recover!",
  verify: "Verified!",
  reward: "Unlocked!",
});

const COPY_LABELS = Object.freeze({
  prompt: "Prompt",
  command: "Command",
});

if (typeof document !== "undefined") {
  initializeDemo(document);
  initializeCopyButtons(document);
}

export function initializeDemo(doc, options = {}) {
  const arena = doc.querySelector("#arena-demo");
  if (!arena) return;

  const duelButton = doc.querySelector("#duel-button");
  const replayButton = doc.querySelector("#replay-button");
  const skipButton = doc.querySelector("#skip-button");
  const phaseTitle = doc.querySelector("#phase-title");
  const phaseCopy = doc.querySelector("#phase-copy");
  const missionLabel = doc.querySelector("#mission-label");
  const demoStatus = doc.querySelector("#demo-status");
  const duelCue = doc.querySelector("#duel-cue");
  const reward = doc.querySelector("#reward");
  const missionButtons = Array.from(doc.querySelectorAll("[data-mission]"));
  const teamLabels = Array.from(doc.querySelectorAll("[data-team-label]"));
  const steps = Array.from(doc.querySelectorAll("[data-step]"));
  const reducedMotionQuery = Object.hasOwn(options, "motionQuery")
    ? options.motionQuery
    : getReducedMotionQuery();
  let reducedMotion = Boolean(reducedMotionQuery && reducedMotionQuery.matches);

  let state = createInitialState();
  let beat = "ready";
  let timeline = null;
  let rewardMotionAllowed = false;
  const initialDuelMarkup = duelButton ? duelButton.innerHTML : "";

  if (demoStatus) demoStatus.setAttribute("aria-live", "polite");

  function render() {
    const phaseContent = PHASE_CONTENT[state.phase];
    const teams = MISSION_TEAMS[state.mission];
    arena.dataset.phase = state.phase;
    arena.dataset.beat = beat;
    arena.dataset.reducedMotion = String(reducedMotion);
    arena.dataset.rewardMotion = String(rewardMotionAllowed);

    if (phaseTitle) phaseTitle.textContent = phaseContent.title;
    if (phaseCopy) {
      phaseCopy.textContent =
        state.phase === "compare"
          ? "Demo: " + teams.a + " vs. " + teams.b + "."
          : phaseContent.copy;
    }
    if (missionLabel) missionLabel.textContent = MISSION_LABELS[state.mission];
    setTextIfChanged(demoStatus, phaseContent.status);
    setTextIfChanged(duelCue, DUEL_CUES[beat] || "Ready!");
    if (reward) reward.hidden = state.phase !== "complete";
    if (replayButton) replayButton.hidden = state.phase !== "complete";
    if (duelButton) {
      duelButton.hidden = state.phase === "complete";
      duelButton.disabled = state.phase !== "idle";
      if (state.phase === "compare" || state.phase === "validate") {
        duelButton.textContent = "Dueling…";
      } else if (duelButton.innerHTML !== initialDuelMarkup) {
        duelButton.innerHTML = initialDuelMarkup;
      }
      if (duelButton.hidden) duelButton.disabled = true;
    }
    if (skipButton) {
      const active = state.phase === "compare" || state.phase === "validate";
      skipButton.hidden = !active;
      skipButton.disabled = !active;
    }

    for (const label of teamLabels) {
      if (label.dataset.teamLabel === "a") label.textContent = teams.a;
      if (label.dataset.teamLabel === "b") label.textContent = teams.b;
    }

    for (const button of missionButtons) {
      const mission = button.dataset.mission;
      const validMission = Object.hasOwn(MISSION_LABELS, mission);
      const selected = mission === state.mission;

      button.disabled = state.phase === "compare" || state.phase === "validate";
      button.setAttribute("aria-pressed", String(selected));
      if (validMission) {
        button.setAttribute(
          "aria-label",
          "Select mission: " + MISSION_LABELS[mission],
        );
      }
    }

    for (const step of steps) {
      const active = step.dataset.step === state.phase;
      step.dataset.active = String(active);
      if (active) {
        step.setAttribute("aria-current", "step");
      } else {
        step.removeAttribute("aria-current");
      }
    }
  }

  function applyTimelinePhase(phase) {
    if (phase === "validate" && state.phase === "compare") {
      state = reduceArenaState(state, { type: "advance" });
    } else if (phase === "complete") {
      const shouldFocusReplay = Boolean(
        skipButton && replayButton && doc.activeElement === skipButton,
      );
      while (state.phase !== "complete") {
        const nextState = reduceArenaState(state, { type: "advance" });
        if (nextState === state) break;
        state = nextState;
      }
      render();
      if (shouldFocusReplay) replayButton.focus({ preventScroll: true });
      timeline = null;
      return;
    }

    render();
  }

  if (duelButton) {
    duelButton.addEventListener("click", function () {
      if (state.phase !== "idle") return;

      const shouldFocusSkip =
        skipButton &&
        (doc.activeElement === duelButton || doc.activeElement === doc.body);
      state = reduceArenaState(state, { type: "start" });
      beat = "ready";
      rewardMotionAllowed = !reducedMotion;
      render();
      if (shouldFocusSkip && !skipButton.hidden) {
        skipButton.focus({ preventScroll: true });
      }

      timeline = scheduleDuelTimeline({
        ...options.scheduleOptions,
        reducedMotion,
        onPhase: applyTimelinePhase,
        onBeat(nextBeat) {
          beat = nextBeat;
          render();
        },
      });
    });
  }

  if (replayButton) {
    replayButton.addEventListener("click", function () {
      if (timeline) timeline.cancel();
      timeline = null;
      state = reduceArenaState(state, { type: "replay" });
      beat = "ready";
      render();
      if (duelButton && !duelButton.hidden) duelButton.focus();
    });
  }

  if (skipButton) {
    skipButton.addEventListener("click", function () {
      if (
        timeline &&
        (state.phase === "compare" || state.phase === "validate")
      ) {
        timeline.finish();
      }
    });
  }

  for (const button of missionButtons) {
    button.addEventListener("click", function () {
      const mission = button.dataset.mission;
      if (!Object.hasOwn(MISSION_LABELS, mission)) return;

      state = reduceArenaState(state, {
        type: "select-mission",
        mission: mission,
      });
      if (state.phase === "idle") beat = "ready";
      render();
    });
  }

  if (reducedMotionQuery) {
    const onMotionPreferenceChange = (event) => {
      const nextReducedMotion = Boolean(event.matches);
      if (nextReducedMotion === reducedMotion) return;
      reducedMotion = nextReducedMotion;
      if (reducedMotion) rewardMotionAllowed = false;
      render();
      if (timeline) timeline.finish();
    };

    if (typeof reducedMotionQuery.addEventListener === "function") {
      reducedMotionQuery.addEventListener("change", onMotionPreferenceChange);
    } else if (typeof reducedMotionQuery.addListener === "function") {
      reducedMotionQuery.addListener(onMotionPreferenceChange);
    }
  }

  render();
}

function initializeCopyButtons(doc) {
  const copyStatus = doc.querySelector("#copy-status");
  const copyButtons = Array.from(doc.querySelectorAll("[data-copy]"));
  const fields = {
    prompt: doc.querySelector("#install-prompt"),
    command: doc.querySelector("#install-command"),
  };

  if (copyStatus) copyStatus.setAttribute("aria-live", "polite");

  for (const button of copyButtons) {
    const kind = button.dataset.copy;
    if (!Object.hasOwn(COPY_LABELS, kind)) continue;

    button.addEventListener("click", function () {
      copyField(kind, fields[kind], copyStatus);
    });
  }
}

export async function copyField(kind, field, status) {
  const label = COPY_LABELS[kind];
  if (!field) {
    setStatus(status, label + " text is unavailable.");
    return;
  }

  try {
    const clipboard = globalThis.navigator && globalThis.navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") {
      throw new Error("Clipboard API unavailable");
    }

    await clipboard.writeText(field.value);
    setStatus(status, label + " copied.");
  } catch {
    let selected = false;
    try {
      field.focus();
      field.select();
      if (typeof field.setSelectionRange === "function") {
        field.setSelectionRange(0, field.value.length);
      }
      selected = true;
    } catch {
      selected = false;
    }

    if (selected) {
      setStatus(
        status,
        "Clipboard unavailable. Text selected; use your copy shortcut (Ctrl+C or ⌘C).",
      );
    } else {
      setStatus(
        status,
        "Clipboard unavailable. Select the text above and use your copy shortcut (Ctrl+C or ⌘C).",
      );
    }
  }
}

function setStatus(element, message) {
  if (element) element.textContent = message;
}

function getReducedMotionQuery() {
  try {
    if (typeof globalThis.matchMedia === "function") {
      return globalThis.matchMedia("(prefers-reduced-motion: reduce)");
    }
  } catch {
    return null;
  }
  return null;
}

function setTextIfChanged(element, text) {
  if (element && element.textContent !== text) element.textContent = text;
}
