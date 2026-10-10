const makeStep = (phase, beat, duration) =>
  Object.freeze({ phase, beat, duration });

export const DUEL_TIMELINE = Object.freeze([
  makeStep("compare", "ready", 500),
  makeStep("compare", "blue-attack", 700),
  makeStep("compare", "red-block", 550),
  makeStep("compare", "red-attack", 700),
  makeStep("compare", "blue-block", 550),
  makeStep("compare", "clash", 850),
  makeStep("compare", "recover", 550),
  makeStep("validate", "verify", 1200),
  makeStep("complete", "reward", null),
]);

export const REDUCED_MOTION_TIMELINE = Object.freeze([
  makeStep("compare", "ready", 350),
  makeStep("validate", "verify", 350),
  makeStep("complete", "reward", null),
]);

export function createDuelTimeline({ reducedMotion = false } = {}) {
  return reducedMotion ? REDUCED_MOTION_TIMELINE : DUEL_TIMELINE;
}

export function scheduleDuelTimeline({
  setTimeout: schedule = globalThis.setTimeout.bind(globalThis),
  clearTimeout: cancelTimer = globalThis.clearTimeout.bind(globalThis),
  onPhase = () => {},
  onBeat = () => {},
  onComplete = () => {},
  reducedMotion = false,
} = {}) {
  if (typeof schedule !== "function" || typeof cancelTimer !== "function") {
    throw new TypeError("Duel timeline requires timer functions");
  }

  const timeline = createDuelTimeline({ reducedMotion });
  let index = 0;
  let timer = null;
  let generation = 0;
  let settled = false;

  function clearPendingTimer() {
    generation += 1;
    if (timer !== null) {
      cancelTimer(timer);
      timer = null;
    }
  }

  function emitStep(step) {
    if (!step || settled) return;

    onPhase(step.phase);
    onBeat(step.beat);

    if (step.duration === null) {
      settled = true;
      clearPendingTimer();
      onComplete();
      return;
    }

    const expectedGeneration = ++generation;
    timer = schedule(() => {
      if (settled || expectedGeneration !== generation) return;
      timer = null;
      index += 1;
      emitStep(timeline[index]);
    }, step.duration);
  }

  function finish() {
    if (settled) return false;
    clearPendingTimer();
    index = timeline.length - 1;
    emitStep(timeline[index]);
    return true;
  }

  function cancel() {
    if (settled) return false;
    settled = true;
    clearPendingTimer();
    return true;
  }

  emitStep(timeline[0]);
  return Object.freeze({ finish, skip: finish, cancel });
}
