# Security model

## Purpose

Verified-Human is an explainable screening prototype for participant recruitment. It aggregates
signals that may warrant review; it does not establish that a participant is a real person or that
they acted fraudulently.

## What the demo observes

| Signal family | Example evidence | Intended use |
| --- | --- | --- |
| Behavioral telemetry | Completion time, cadence variance, paste activity, focus changes | Identify patterns that are atypical for the configured task. |
| Semantic trap | Compliance with an impossible premise versus a clear refutation | Surface possible automated or inattentive responses. |
| Footprint integrity | Account age, repository count, follower count | Illustrate how an external reputation signal might inform review. |

## Important boundaries

- All profiles and footprint values in the sandbox are simulated.
- Client-side telemetry can be manipulated by a participant with control of their browser. The demo
  checksum is not an authenticated server-side anti-tamper mechanism.
- Heuristics can produce false positives. A score should initiate review, not make an irreversible
  decision by itself.
- Semantic patterns are context-dependent and should be evaluated for language, accessibility,
  culture, and task-specific bias before production use.
- The project intentionally makes no live external API calls and stores no participant data.

## Production work required

1. Define lawful consent, retention, deletion, and appeal procedures for participant data.
2. Move telemetry validation and signed session challenges to a server-controlled trust boundary.
3. Independently assess the scoring model for accuracy, disparate impact, and adversarial evasion.
4. Add authenticated data sources with rate limits, provenance, and privacy review before any OSINT integration.
5. Keep a human reviewer in the final decision path and audit overrides.
