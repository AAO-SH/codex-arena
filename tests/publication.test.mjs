import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const read = (name) => readFile(path.join(root, name), "utf8");

test("HTML and CSS local assets exist and work below a project subpath", async () => {
  const html = await read("index.html");
  const css = await read("styles.css");
  const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1]);
  refs.push(
    ...[...css.matchAll(/url\(['"]?([^'"\)]+)['"]?\)/g)].map((m) => m[1]),
  );
  for (const ref of refs) {
    if (/^(https?:|#)/.test(ref)) continue;
    assert.ok(
      !ref.startsWith("/"),
      `Absolute path breaks project hosting: ${ref}`,
    );
    await stat(path.join(root, ref.split("#")[0]));
  }
});

test("fragment links have real targets and IDs are unique", async () => {
  const html = await read("index.html");
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, fragment] of html.matchAll(/href="#([^"]+)"/g)) {
    assert.ok(ids.includes(fragment), `Missing anchor: ${fragment}`);
  }
});

test("publication declares English, its domain, and GitHub source installation", async () => {
  const html = await read("index.html");
  assert.match(html, /<html lang="en">/);
  assert.match(html, /No models run here/);
  assert.match(
    html,
    /git clone https:\/\/github\.com\/AAO-SH\/codex-arena\.git/,
  );
  assert.match(html, /--workspace \. --bootstrap/);
  assert.equal((await read("CNAME")).trim(), "arena.aao.sh");
  await stat(path.join(root, ".nojekyll"));
  await stat(path.join(root, "assets/fonts/OFL-Fredoka.txt"));
});
