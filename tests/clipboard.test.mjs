import { test } from "node:test";
import assert from "node:assert/strict";
import { copyField } from "../js/app.js";

async function withClipboard(clipboard, fn) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { clipboard },
  });
  try {
    await fn();
  } finally {
    if (previous) Object.defineProperty(globalThis, "navigator", previous);
    else delete globalThis.navigator;
  }
}

test("copy only reports success after the clipboard write resolves", async () => {
  let finish;
  let received;
  const done = new Promise((resolve) => {
    finish = resolve;
  });
  const status = { textContent: "Waiting" };
  await withClipboard(
    {
      writeText: (text) => {
        received = text;
        return done;
      },
    },
    async () => {
      const pending = copyField(
        "prompt",
        { value: "Install in this workspace" },
        status,
      );
      assert.equal(status.textContent, "Waiting");
      finish();
      await pending;
      assert.equal(received, "Install in this workspace");
      assert.equal(status.textContent, "Prompt copied.");
    },
  );
});

test("denied clipboard selects the exact command and offers manual recovery", async () => {
  const status = { textContent: "" };
  const calls = [];
  const field = {
    value: "git clone example",
    focus: () => calls.push("focus"),
    select: () => calls.push("select"),
    setSelectionRange: (a, b) => calls.push([a, b]),
  };
  await withClipboard(
    {
      writeText: async () => {
        throw new Error("NotAllowedError");
      },
    },
    async () => {
      await copyField("command", field, status);
      assert.deepEqual(calls, ["focus", "select", [0, field.value.length]]);
      assert.match(status.textContent, /Clipboard unavailable.*Ctrl\+C/);
      assert.doesNotMatch(status.textContent, /copied/);
    },
  );
});

test("missing clipboard and selection support still provide a recovery message", async () => {
  const status = { textContent: "" };
  await withClipboard(undefined, async () => {
    await copyField("prompt", { value: "Install" }, status);
    assert.match(status.textContent, /Select the text above/);
  });
});
