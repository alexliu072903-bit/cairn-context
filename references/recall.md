# Recall relevant decisions

Use this route when the task depends on previous decisions or when the user asks what was decided.

## Establish scope

1. Read `<repository>/AGENTS.md`.
2. Identify the project that owns the work and read its `README.md` and `state.md`. If scope remains ambiguous, inspect the project list before asking. A configured default does not establish scope.
3. Reuse adequate context already in the current conversation (L1). For a known ID, the original wording or rationale, a conflict, a correction/revocation/replacement, or a high-impact decision, go directly to the source (L3) with exact `get`. Use `list` first if an exact ID must be located.

## Use a thread brief for ordinary recall

On an L1 miss, use the host's short-lived candidate brief (L2). Choose a few literal terms from the task, including meaningful alternative names or Chinese phrases. If the host provides a stable thread ID, use it; otherwise keep a single opaque identifier for this thread's lifetime.

- **Build:** `brief --project <project> --thread <thread> --focus <term>`. Repeat `--focus` for alternatives. Use the same repository on every call. Keep the full result in this thread's context, not in a shared or durable cache.
- **Check before reuse:** pass the entire prior result on stdin to `brief-check --project <project> --thread <thread>`. Only `fresh` with `next_action: use_brief` permits ordinary reuse, after reviewing warnings and confirming the candidates cover the task.
- **Rebuild:** a stale brief must be discarded. A change of repository, project, thread, focus or limit requires a new brief, not relabeling the old one. A refusal or unrecognized response never authorizes reuse. For pending writes, follow [recovery](operations.md).

A brief contains only literal candidates from valid decisions, with bounded excerpts. `complete` describes source read completeness; semantic coverage is unknown. A successful check establishes equality to the current snapshot, not fitness for the task.

## Fall back to source evidence

- If candidates are absent, insufficient, result-limited, or the read is incomplete, navigate with `list --project <project>`, then open relevant IDs with `get --project <project> --id <id>`. Continue list pages with the same filters and the returned snapshot. Never conclude that no decisions exist from an empty brief.
- When a candidate's decision headline, scope, exclusions or overturn conditions are truncated, use exact `get` to read the full source before adopting it as a current constraint. Read the missing text from the record without inferring it from the excerpt. An otherwise unchanged brief returns `fresh` with `next_action: read_source`.
- Inspect warnings even when `complete:true`. Use `get` if a warning or scope ambiguity affects the task. Continue section slices with the original revision.
- A `valid` decision is current only within its recorded scope and exclusions. Date alone does not resolve conflicting records. Superseded and revoked records explain history; use exact `get` to follow successor links.
- `list` reads current files even if the generated Markdown index is stale. A current user correction or explicit replacement goes through the [record route](record.md).

See [access.md](access.md) for command syntax and response fields.

## Older repositories

If the unified CLI lacks `brief`/`brief-check`, use `list` and `get` directly. If `scripts/cairn.py` is absent, read `decisions-index.md` and the relevant original files under the installed Protocol. Report the missing capabilities and do not imply that the older workflow has the same snapshot and recovery guarantees.
