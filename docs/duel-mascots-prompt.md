# Duel Mascots Sprite Atlas

## Provenance

- Generated with the built-in Codex ImageGen tool, using `assets/images/arena-scene.png` as a visual reference for the mascot identity and illustration style.
- Final asset: `assets/images/duel-mascots.png`
- Canvas: 1774 × 887 px, PNG with 32-bit RGBA transparency. The canvas is exactly 2:1 and is divided into two 887 × 887 px square frames.
- The blue mascot occupies the left frame and faces right. The coral mascot occupies the right frame and faces left. Both have matching scale and centered silhouettes with transparent breathing room.
- The generated result was visually inspected. No pixel editing or resizing was applied after generation.

## Initial generation prompt

Use case: stylized-concept. Asset type: transparent two-frame sprite atlas for a website duel animation. Input image: the provided arena image is a reference only for character identity and illustration style. Isolate and redraw its two small mascot fighters as clean character-only cutouts, preserving their identity. One wide atlas exactly 2:1, arranged as two equal square panels side by side. Left panel: rounded white ghost-robot with bold navy outline, navy face visor and circular headset, bright blue tied headband with both long tails complete, looking right. Right panel: same mascot design and visual scale, coral-red tied headband with both tails complete, looking left. Both stand upright in friendly playful guard poses with hands raised, facing each other. Center the left character exactly at 25% of full atlas width and right character exactly at 75%, same baseline, same vertical center and scale. Each full silhouette including tails stays entirely within its own square, with at least 12% transparent clear margin from each panel's edges; leave a clean transparent center seam. Polished 2D cartoon matching the reference's smooth white shading, crisp dark navy outlines, soft highlights, saturated blue/coral accents. Genuine transparent alpha. No scene, ground, floor shadows, text, labels, UI, logos, extra characters, weapons, effects, motion streaks, dividers, borders, cropping, or cross-seam overlap.

## Refinement prompt

Edit the provided two-character atlas. Preserve the existing clean transparent canvas, exact composition, character identities, colors, outline style, poses, and facing directions. Change only the scale and spacing: uniformly reduce each entire mascot, including all headband tails, to about 72% of its current size, and center them precisely in their respective left and right halves at 25% and 75% of the full canvas width. Keep the pair equal in scale and on the same vertical centerline, leaving generous empty transparent margin around every silhouette, especially at the outer edges and center seam. Keep the same canvas aspect ratio and show exactly two full characters. No new elements, no background, no border, no text, no crop.
