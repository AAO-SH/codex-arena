import {
  createInitialState,
  MISSION_LABELS,
  reduceArenaState,
} from "./arena-state.js";

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
    status: "Illustrated demo: comparing two approaches.",
  },
  validate: {
    title: "Time to verify",
    copy: "Demo: Test the method against a baseline.",
    status: "Illustrated demo: test the method against a baseline.",
  },
  complete: {
    title: "Playbook unlocked",
    copy: "Demo: reusable scripts and instructions, ready to use.",
    status: "Playbook unlocked. Replay to watch again.",
  },
});

const COPY_LABELS = Object.freeze({
  prompt: "Prompt",
  command: "Command",
});

if (typeof document !== "undefined") {
  initializeDemo(document);
  initializeCopyButtons(document);
}

function initializeDemo(doc) {
  const arena = doc.querySelector("#arena-demo");
  if (!arena) return;

  const duelButton = doc.querySelector("#duel-button");
  const replayButton = doc.querySelector("#replay-button");
  const phaseTitle = doc.querySelector("#phase-title");
  const phaseCopy = doc.querySelector("#phase-copy");
  const missionLabel = doc.querySelector("#mission-label");
  const demoStatus = doc.querySelector("#demo-status");
  const reward = doc.querySelector("#reward");
  const missionButtons = Array.from(doc.querySelectorAll("[data-mission]"));
  const teamLabels = Array.from(doc.querySelectorAll("[data-team-label]"));
  const steps = Array.from(doc.querySelectorAll("[data-step]"));
  const duration = getPhaseDuration();

  let state = createInitialState();
  let timer = null;
  let runId = 0;

  if (demoStatus) demoStatus.setAttribute("aria-live", "polite");

  function render() {
    const phaseContent = PHASE_CONTENT[state.phase];
    const teams = MISSION_TEAMS[state.mission];
    arena.dataset.phase = state.phase;

    if (phaseTitle) phaseTitle.textContent = phaseContent.title;
    if (phaseCopy) {
      phaseCopy.textContent =
        state.phase === "compare"
          ? "Demo: " + teams.a + " vs. " + teams.b + "."
          : phaseContent.copy;
    }
    if (missionLabel) missionLabel.textContent = MISSION_LABELS[state.mission];
    if (demoStatus) demoStatus.textContent = phaseContent.status;
    if (reward) reward.hidden = state.phase !== "complete";
    if (replayButton) replayButton.hidden = state.phase !== "complete";
    if (duelButton) {
      duelButton.hidden = state.phase === "complete";
      duelButton.disabled = state.phase !== "idle";
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

  function clearTimer() {
    if (timer !== null) {
      globalThis.clearTimeout(timer);
      timer = null;
    }
  }

  function scheduleNext(expectedRunId) {
    timer = globalThis.setTimeout(function () {
      timer = null;
      if (expectedRunId !== runId) return;

      const focusRemainsInDemo =
        doc.activeElement === duelButton || doc.activeElement === doc.body;
      state = reduceArenaState(state, { type: "advance" });
      render();
      if (state.phase === "complete" && focusRemainsInDemo && replayButton) {
        replayButton.focus({ preventScroll: true });
      }

      if (state.phase === "validate") {
        scheduleNext(expectedRunId);
      }
    }, duration);
  }

  if (duelButton) {
    duelButton.addEventListener("click", function () {
      if (state.phase !== "idle") return;

      clearTimer();
      state = reduceArenaState(state, { type: "start" });
      runId += 1;
      const currentRun = runId;
      render();
      scheduleNext(currentRun);
    });
  }

  if (replayButton) {
    replayButton.addEventListener("click", function () {
      clearTimer();
      runId += 1;
      state = reduceArenaState(state, { type: "replay" });
      render();
      if (duelButton && !duelButton.hidden) duelButton.focus();
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
      render();
    });
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

function getPhaseDuration() {
  try {
    if (
      typeof globalThis.matchMedia === "function" &&
      globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return 400;
    }
  } catch {
    // Use the normal short demo duration when matchMedia is unavailable.
  }

  return 1100;
}
