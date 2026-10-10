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
