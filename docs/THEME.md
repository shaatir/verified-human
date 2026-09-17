# Interface theme

## Intent

The interface behaves like a calm analyst console. It makes evidence legible before it asks for a
decision, and it gives prototype limitations as much visual weight as positive detection signals.

## Foundations

| Token | Use |
| --- | --- |
| `--bg-base` / `--bg-surface` | Deep neutral operational surfaces. |
| `--color-primary` | Cyan-blue signal for active navigation and inspectable evidence. |
| `--color-approved`, `--color-flagged`, `--color-rejected` | Decision states only; never decorative color. |
| `--font-sans` | Product and narrative text. |
| `--font-mono` | Status labels, signal indexes, and technical values. |
| `--radius-sm` / `--radius-md` | Compact controls and panels. |

## Rules

- Lead with what the system observes, not a claim of certainty.
- Use clear status words and exposed rules instead of color alone.
- Keep the home screen unframed and concise; reserve panels for operator workflows.
- Label all mock data and client-side demonstration mechanics plainly.
