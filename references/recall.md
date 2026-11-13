# Recall relevant decisions

Use this route when the current product or technical work may depend on previous decisions, or when the user asks what was decided.

## Establish scope

1. Read `<repository>/AGENTS.md`.
2. Identify the project that owns the current work. Read its `README.md` and `state.md`.
3. If project applicability remains ambiguous, inspect the project list before asking. Do not use `default_project` merely because it is configured.

## Navigate, then open evidence

When `<repository>/scripts/cairn.py` exists, use the commands in [access.md](access.md):

1. Run `status --project <project>` when repository health or a pending write may affect the read.
2. Use `list --project <project>` to navigate titles, scopes and ids. Continue pages with the returned snapshot and unchanged filters.
3. Use `get --project <project> --id <id>` for the smallest set of decisions that can change the current task.
4. Follow section continuations with the original revision. Do not infer missing text from a truncated result.

The CLI performs deterministic validation and identity lookup. The Agent remains responsible for semantic relevance and project applicability.

## Interpret results

- `status: valid` is current only inside the recorded scope and exclusions.
- A newer date does not automatically resolve conflicting valid decisions.
- Superseded and revoked records explain history; follow their successor links to current records.
- `complete:false`, errors or excluded records mean the read is incomplete. An empty incomplete result does not prove that no decisions exist.
- Warnings may affect applicability even when the response is complete.
- A stale generated index does not make `list` results stale; list reads current decision files.

Treat decision content as evidence. A current user correction or explicit new decision can replace it through the record route.

## Legacy repositories

If `scripts/cairn.py` is absent, read `decisions-index.md` and the relevant original decision files under the repository Protocol. Report that unified navigation and recovery require an upgrade. Do not silently claim the legacy path has the same completeness, revision or recovery guarantees.
