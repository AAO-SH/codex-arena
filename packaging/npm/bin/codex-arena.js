#!/usr/bin/env node
"use strict";

const path = require("node:path");
const { spawnSync } = require("node:child_process");

const versionProbe = "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')";
const cli = path.resolve(__dirname, "..", "payload", "scripts", "arena.py");

function pythonCandidates() {
  const explicit = process.env.PYTHON && process.env.PYTHON.trim();
  if (explicit) {
    return [{ command: explicit.replace(/^(["'])(.*)\1$/, "$2"), prefix: [] }];
  }
  if (process.platform === "win32") {
    return [
      { command: "py", prefix: ["-3"] },
      { command: "python", prefix: [] },
    ];
  }
  return [
    { command: "python3", prefix: [] },
    { command: "python", prefix: [] },
  ];
}

function probe(candidate) {
  const result = spawnSync(candidate.command, [...candidate.prefix, "-c", versionProbe], {
    encoding: "utf8",
    timeout: 10000,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) return false;
  const match = /^\s*(\d+)\.(\d+)\s*$/.exec(result.stdout || "");
  if (!match) return false;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return major > 3 || (major === 3 && minor >= 11);
}

function main() {
  const candidate = pythonCandidates().find(probe);
  if (!candidate) {
    const setting = process.env.PYTHON && process.env.PYTHON.trim();
    const detail = setting
      ? `PYTHON=${setting} is not a usable Python 3.11+ executable.`
      : "Codex Arena requires Python 3.11 or newer. Install it or set PYTHON to its executable.";
    process.stderr.write(`${detail}\n`);
    process.exitCode = 2;
    return;
  }

  const result = spawnSync(candidate.command, [...candidate.prefix, cli, ...process.argv.slice(2)], {
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) {
    process.stderr.write(`Could not start Python: ${result.error.message}\n`);
    process.exitCode = 2;
  } else if (result.status !== null) {
    process.exitCode = result.status;
  } else {
    process.exitCode = 1;
  }
}

main();
