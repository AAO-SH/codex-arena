# Duel motion

The user's requested game-like sequence is the only focal animation. It starts on a button press, runs once, and ends in a persistent playbook reward.

- Separate a clean arena background from a transparent two-character sprite atlas.
- Show alternating blue/red lunges, defensive shields, recovery and a friendly clash.
- Follow the exchange with verification and a book reveal, short light rays and a finite confetti burst.
- Keep the existing English copy, installation flow and illustrative-demo disclosure.
- Provide a skip control and deterministic cancellation for replay and preference changes.
- Reduced motion replaces the exchange with brief static state changes; no lunges, particles or spatial reward effect.

Implementation uses local assets, CSS keyframes and a small JavaScript timeline with injected timers for tests. No animation library, audio, API calls or generated metrics are needed.
