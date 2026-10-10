# Pocket Arena — design

Codex Arena is introduced as a small, playful game world. The page gives visitors a quick picture of how competing strategies can become reusable playbooks, then offers a direct way to install the skill in a Codex workspace.

## Visual direction

- Use a pale sky background, cream and gold surfaces, navy outlines, rounded corners, and soft shadows.
- Keep the existing Codex Arena logo and the blue and red robot pets. A cartoon coliseum anchors the interactive demo; the playbook illustration ties the installation area back to the arena.
- Use the locally hosted Fredoka font for display text and a system sans-serif for functional copy. Keep the copy short and readable.
- On wide screens, place the headline beside the arena. On small screens, stack the headline, arena, process steps, and installation card in that order.

## Visitor flow

Visitors choose a demo quest, watch a three-part walkthrough comparing approaches and checking a result, then see a playbook reward. The walkthrough is illustrative: it runs no models and presents no real tournament measurements. Visitors can replay it or choose another quest.

The arena separates the background from a transparent two-mascot sprite atlas. A finite 5.6-second timeline animates alternating lunges and shields, a friendly clash, recovery, and verification. The reward book pops into view with a short ray and confetti burst. A Skip control ends the sequence immediately. No sounds or perpetual loops are added. Reduced motion uses static ready/verify states and a still reward; changing that preference during a duel cancels the remaining movement.

The installation card offers three compact, game-menu choices: Ask Codex, npm, and PyPI. Each reveals its own copyable prompt or commands, requirements, and package link. A source install stays in a disclosure. All methods target the visitor's current project folder. Without JavaScript the methods remain readable together. Installation does not start a tournament.

## Interaction and accessibility

- Use native links, buttons, and a labelled mission group so the page works with a keyboard and assistive technology.
- Show a visible focus indicator, provide a skip link, and announce demo and clipboard status changes.
- Respect reduced-motion preferences for transitions and animation. Keep the demo usable when motion is reduced.
- If clipboard access is unavailable, select the requested text and explain the manual copy shortcut.

## Publishing constraints

The site is static HTML, CSS, and native JavaScript for GitHub Pages. Keep fonts and images local, use relative asset paths so the site also works below a project subpath, and avoid a build step.
