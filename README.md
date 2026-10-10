# Codex Arena · Website

The playful, static home of [Codex Arena](https://github.com/AAO-SH/codex-arena), by [AAO.sh](https://aao.sh).

**Visit [arena.aao.sh](https://arena.aao.sh).** For the skill, installer, and tournament engine, use the repository's [`main` branch](https://github.com/AAO-SH/codex-arena/tree/main).

## This branch

`gh-pages` starts from an empty root commit and contains only the website. The interface is in English. HTML, CSS, and JavaScript run directly in the browser; no framework, build step, API keys, analytics, or remote runtime dependencies.

- Three illustrative quests: fix a bug, review code, organize knowledge.
- Animated mascot attacks and shield blocks in a short strategy duel.
- A celebratory playbook unlock, with skip, replay, and reduced-motion controls.
- Copyable Codex prompt, npm and PyPI installation commands, and a source option for any workspace.
- Responsive layout, keyboard controls, reduced-motion support, and a manual copy fallback.

The demo makes **no model calls** and produces no measured tournament results. Installing the skill does not start a tournament.

## Preview and test

From this folder, with Python 3.11+:

```sh
python -m http.server 4173 --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/`. ES modules need an HTTP server; do not open `index.html` with a `file://` URL.

With Node.js 22+:

```sh
npm test
```

No `npm install` is needed. Tests cover the demo state machine, choreography, cancellation, focus handling, clipboard recovery, and integrity of the static publication.

## Publish

GitHub Pages publishes **`gh-pages` → `/`**. `.nojekyll` preserves the static files, and `CNAME` declares `arena.aao.sh`. The domain's CNAME points to `aao-sh.github.io`. Updates are committed and pushed to this branch without merging the website into `main`.

## Edit

| File                  | Purpose                                                   |
| --------------------- | --------------------------------------------------------- |
| `index.html`          | English content, accessibility, installation instructions |
| `styles.css`          | Responsive cartoon theme and motion                       |
| `js/arena-state.js`   | Pure demo state machine                                   |
| `js/duel-timeline.js` | Cancellable choreography and reduced-motion timing        |
| `duel.css`            | Mascot motion, shields, and the finite reward celebration |
| `js/app.js`           | Demo controls and clipboard handling                      |
| `assets/images/`      | Brand, arena scene, reward, favicon                       |
| `assets/fonts/`       | Self-hosted Fredoka and its OFL license                   |
| `docs/`               | Image provenance and verification notes                   |

The npm (`@aao-sh/codex-arena`) and PyPI (`codex-arena`) packages are public. Keep the commands aligned with their CLI entrypoints, preserve the source install option, and retain the illustrative-demo labels.

## Credits

Website code: MIT, © 2026 AAO-SH. Brand assets belong to AAO-SH. The new arena and playbook illustrations were produced with OpenAI's built-in image generation tool using the Codex Arena logo as a visual reference; prompts are in `docs/`. Fredoka is distributed under the SIL Open Font License in `assets/fonts/OFL-Fredoka.txt`.

Codex Arena builds on the ideas of [Jake Schincariol's Arena skill](https://github.com/Jakeschincariol/arena-skill). The engine's attribution and license remain in the main branch.
