# Verification

Checked on 2026-10-10 before the initial website release.

- `npm test`: 13 passing tests. State transitions, invalid states, completed-mission reset, clipboard success ordering and failure recovery, local asset paths, internal links, English document language, domain declaration, and source installation command.
- `node --check js/app.js`: valid JavaScript.
- In-app Chromium: desktop at 1440px and mobile at 390px inspected visually. Additional 320px viewport check found no overflowing buttons or horizontal page overflow.
- Quest selection updates the strategy labels; the demo reaches the book reward; replay resets the state; keyboard focus moves to Replay on completion and back to Start on replay.
- Both installation copy buttons display success after the Clipboard API resolves. Manual fallback is verified in unit tests. Terminal instructions expand inline.
- All images load; no browser console warnings/errors were recorded during local testing.
- Reduced motion is implemented in CSS and the demo timer. A system-level reduced-motion browser emulation was not available in this test session.
- Installation arguments were checked against the skill's current CLI source. The website test does not install the skill or run paid inference.

## Scope and limitations

The walkthrough is explicitly illustrative. It does not run a tournament or generate a validated playbook. The PNG artwork preserves the generated assets' quality; the three raster assets total approximately 4 MB, so this is not a performance benchmark or an assertion of optimal mobile payload. Font and image files are hosted locally.

Independent review found a focus handoff issue and a platform-specific copy-shortcut message; both were corrected. Hidden reward art now requests lazy loading. Native screenshot stitching can display the off-screen skip link in a full-page capture; the actual viewport and its DOM bounds were verified separately.

## Animated duel update — 2026-10-10

- `npm test`: 22 passing tests, including timeline boundaries, cancellation, stale callbacks, skip/replay, a live motion-preference change, and focus preservation when a visitor leaves the duel controls. Enabling motion after a reduced-motion reward cannot restart the celebration; a new duel can animate normally.
- JavaScript syntax checks and `git diff --check` passed.
- In-app Chromium: the blue lunge and red shield were observed in motion, with nonidentity transforms and the shield visible during the block. The book reveal and finite confetti animation were confirmed through rendered styles; the persistent reward was inspected visually.
- Skip unlocks the book immediately, clears the timeline, and focuses Replay. Replay restores Start and supports another sequence.
- Desktop at 1440px and mobile at 390px were visually inspected. A 320px check found no horizontal page overflow, and the book and Replay button remained inside the viewport.
- All loaded images resolved. No console errors or warnings were recorded in the updated local demo.
- Reduced motion has deterministic timer tests and CSS guards. System-level browser emulation remains outside the checks performed in this session.
- The update adds a transparent mascot atlas and a clean arena background. The old composite scene remains as source artwork but is not loaded by the page.
