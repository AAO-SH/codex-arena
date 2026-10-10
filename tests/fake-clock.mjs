export function createFakeClock() {
  let now = 0;
  let nextId = 0;
  const pending = new Map();
  const cleared = [];

  return {
    setTimeout(callback, delay) {
      const task = { id: ++nextId, at: now + delay, callback };
      pending.set(task.id, task);
      return task.id;
    },
    clearTimeout(id) {
      const task = pending.get(id);
      if (task) {
        pending.delete(id);
        cleared.push(task);
      }
    },
    tick(duration) {
      const target = now + duration;
      while (true) {
        const task = [...pending.values()]
          .filter((candidate) => candidate.at <= target)
          .sort((a, b) => a.at - b.at || a.id - b.id)[0];
        if (!task) break;
        pending.delete(task.id);
        now = task.at;
        task.callback();
      }
      now = target;
    },
    fireCleared() {
      for (const task of cleared.splice(0)) task.callback();
    },
    get pendingCount() {
      return pending.size;
    },
  };
}
