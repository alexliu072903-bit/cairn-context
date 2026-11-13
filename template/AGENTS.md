# Cairn Project Memory

This repository stores durable project context for agents.

## Start relevant work

1. Read `projects/<project>/README.md`.
2. Read `projects/<project>/state.md`.
3. Use adequate current host Context (L1). If it is insufficient, use a fresh short-lived project/thread brief (L2) for ordinary recall. The host owns the brief and Cairn stores no copy.
4. This repository (L3) is the only source of truth. Use `scripts/cairn.py list`/`get` when the brief is insufficient or incomplete. Use exact `get` directly for known IDs, conflicts, high-impact verification, corrections, revocations or replacements.
5. Follow `protocol/README.md` before recording or changing a decision. Read back the source and discard the affected project's old briefs after a successful write.

## Boundaries

- Record confirmed decisions, not discussions, ordinary tasks, or temporary experiments.
- Preserve decision history when a decision changes.
- Do not store secrets, full conversations, or unrelated personal information.
- Do not publish or change repository visibility without explicit authorization.
