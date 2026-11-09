# Cairn unified access (contract 1)

This is the local CLI contract, bundled with the Skill. It uses Python 3.9+
standard library only. There is no Basic Memory dependency, embedding service,
search ranking, MCP server or hosted account. CLI/Skill are the supported entry
points in this version; a future MCP adapter must use this same contract.

Resolve the user's configured repository first. Below, `<repo>` means that
repository and `<project>` is the project relevant to the current task. Keep
these values explicit; never guess a private repository location.

```bash
python3 <repo>/scripts/cairn.py --repository <repo> projects
python3 <repo>/scripts/cairn.py --repository <repo> status --project <project>
python3 <repo>/scripts/cairn.py --repository <repo> list --project <project>
python3 <repo>/scripts/cairn.py --repository <repo> get --project <project> --id <decision-id>
```

Without `--repository`, configuration uses `CAIRN_CONFIG`, then
`CAIRN_CONFIG_ROOT/config.json`, then `~/.cairn/config.json`. It must contain
`repository`, `identity`, and `default_project`. Unlike the legacy reader, the
new interface never falls back to the directory containing the script. The
configured default does not make an unrelated task belong to that project.

## Read: navigate, then open an exact decision

`list` filters by project, `--status valid|superseded|revoked` (default `valid`),
and optional `--since YYYY-MM-DD`. It returns title, first 140 characters of the
decision, first 240 characters of scope, explicit truncation flags, relative
file path and SHA-256 revision. No semantic selection is performed. Unknown
scope remains empty: it is not inferred from the title.

- `--page` defaults to 1; `--page-size` to 20 (1..200, a per-response bound, not a
  storage limit). `total` and `next_page` make the remaining records discoverable.
- Continue with the returned `--snapshot` and the **same filters/page size**.
  A changed project rejects a stale snapshot. Page 2+ requires a snapshot.
- Results come from current files, not a cached Markdown index. `index: stale`
  does not mean these results are stale. An explicit `reindex --project <id>`
  refreshes the generated Markdown index after validation; ordinary reads do
  not write it.
- `complete:false` and `errors` mean some records were excluded. An empty
  incomplete response is not proof that the project has no decisions. Warnings
  are retained and may matter to applicability even when `complete:true`.
- `get --project <id> --id <decision-id>` resolves that exact identity; it does
  not silently substitute a successor or a similarly named record. The response derives `successors` from the same validated project snapshot, so an
  old record can lead to its replacements without rewriting its original fields. Inspect
  `status`, scope and history before using it as a current constraint.
- `get --metadata` omits sections but returns scope and revision.
- `get --section rationale --offset 0 --limit 2000` returns a character slice
  and `next_offset`. Conclusion, scope, exclusions and overturn conditions
  remain in the envelope. Offsets count Unicode code points, not bytes or
  UTF-16 units. Continue a nonzero offset with `--revision` from the first read; a changed
  revision is refused. Full `get` returns all five normalized sections.

JSON results use `schema:1` (the public source includes `docs/schema/access-output.schema.json` for the shared envelope). `status` returns `state:ready|error|recovery_required`
and reports validation, stale indexes, or a pending request/phase. A successful
status call (`ok:true`) does not assert data quality or write permission.
`capabilities` describes commands, not authorization; actual filesystem and
host access still apply. Every read includes source paths/revisions where
applicable. Existing `read.py` schema 1 is retained for export consumers.

## Write: explicit intent, complete proposal, versioned commit

The Agent must first apply the configured Protocol: explicit durable decision,
project applicability, duplicate/semantic conflict checks, and no invented
rationale. Read the affected records and their revisions. A repeated confirmed
conclusion reuses its existing record; do not submit another `create`.

`write` reads one JSON object from stdin. Use a JSON file or a process pipe, not
shell interpolation of user-authored text:

```bash
python3 <repo>/scripts/cairn.py --repository <repo> write < request.json
```

Example request shape (replace example values and supply full valid Markdown):

```json
{
  "request_id": "session-42-decision-1",
  "project": "demo",
  "action": "supersede",
  "id": "new-choice",
  "confirmed": true,
  "source": "User explicitly replaced old-choice in the current conversation; source reference",
  "expected": {"old-choice": "SHA-256 revision from get"},
  "content": "---\nproject: demo\ndecision: new-choice\nstatus: valid\ndecided_by: Pat\ndecided_at: 2026-11-09\nsupersedes: old-choice\n---\n# New choice\n\n## Decision\nUse the confirmed new choice.\n\n## Rationale\nTo be validated\n\n## Scope\nTo be validated\n\n## Explicitly excluded\nTo be validated\n\n## Overturn signal\nTo be validated\n"
}
```

The `confirmed` flag records the calling Agent's assertion. It does **not** prove
human consent or perform the semantic judgment. Already explicit user intent
needs no redundant approval. Ask once only when intent or scope is ambiguous.
`source` is a bounded reference/explanation, not the entire conversation.

Actions:

- `create`: a new `valid` decision, no history links, empty/omitted `expected`.
- `supersede`: new `valid` content with `supersedes` exactly matching the ids in
  `expected`. All predecessors must be valid and their revisions must match.
  The writer marks them superseded; it preserves their bodies and attribution.
- `revoke`: existing valid `id`, `expected` containing exactly that id/revision;
  no content required. The record is retained with status revoked. Supply the
  user's reason/reference in `source`.
- `correct`: full corrected content for the existing `id`, with its expected
  revision. Status, history links, original author/date are preserved. Original
  and corrected records plus the correction source are appended once to
  `protocol/benchmark/feedback.md`. This fixes a recording error, not a changed
  product choice; a changed choice uses supersede/revoke.

The proposed whole project is validated before writes. Existing project errors
block a new mutation. Missing sections remain warnings under the existing
Protocol; they are not silently promoted to a new hard requirement.

The writer serializes Cairn writers with an OS lock, checks revisions, and saves
a local transaction journal before changing files. It does **not** claim that
multiple filesystem renames form one atomic transaction. Readers refuse a
project while a pending write exists. After read-back validation and index
refresh, the response returns `WRITTEN`, affected addresses/revisions and
warnings. Repeating the same request id/content returns its original receipt;
using that id for different content returns `REQUEST_CONFLICT`.

A receipt describes that operation's completion, not the latest state forever.
Use `get` to inspect later changes. Request IDs prevent retries from duplicating
one operation; they do not detect two differently worded decisions with the
same meaning. That check remains the Skill's responsibility.

## Recovery and external edits

```bash
python3 <repo>/scripts/cairn.py --repository <repo> status --project <project>
python3 <repo>/scripts/cairn.py --repository <repo> recover --project <project> --request-id <id>
```

A pending transaction blocks new writes across the repository, because correction feedback is shared. Recover that request before starting another project's write. Reads of unaffected projects remain available.

Recovery resumes only an existing accepted request. `prepared` may mean none or
some of its records were written; `index_pending` means record writes completed
but index/receipt completion may remain. Retrying the identical `write` also
resumes it. If a file differs from both the recorded before and after state,
recovery returns `RECOVERY_CONFLICT` and preserves it. Do not delete the pending
marker, force a new id, or infer that an I/O error means nothing was written.

Journals are local under `projects/<project>/.cairn/transactions/`; the existing
`.cairn/` ignore rule keeps them out of Git. They contain before/after project
snapshots and the request source: keep them with the private repository. Back
up local state before manually repairing a recovery conflict. Local journals
survive process interruption; this version does not promise power-loss or
cross-machine distributed transaction recovery.

Manual Markdown edits remain supported and are checked on the next read.
Cairn's lock coordinates its own writers, not arbitrary editors or Git. Pause
legacy scheduled sync / avoid Git checkout or rebase during a mutation or
pending recovery; the installer does not enable, alter, or pause autosync.
Concurrent external changes are detected where checked, but an external editor
that ignores the lock is not given a transactional guarantee.

Common refusal codes: `NOT_CONFIGURED`, `PROJECT_NOT_FOUND`, `NOT_FOUND`,
`UNSAFE_PATH`, `INVALID_ARGUMENTS`, `CONFIRMATION_REQUIRED`, `VALIDATION_FAILED`,
`INVALID_STATE`, `ALREADY_EXISTS`, `REVISION_CONFLICT`, `REQUEST_CONFLICT`, `BUSY`,
`RECOVERY_REQUIRED`, `RECOVERY_CONFLICT`, `IO_OR_INPUT_ERROR`.
All handled operation results are JSON; exit 0 means `ok:true`, exit 1 a refusal.
Argparse usage errors exit 2 on stderr. Inspect `complete`, diagnostics and
`state` rather than only the exit code.
