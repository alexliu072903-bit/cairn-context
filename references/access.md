# Cairn unified access (contract 1)

This is the local CLI contract, bundled with the Skill. It uses Python 3.9+
standard library only. There is no Basic Memory dependency, embedding service,
semantic search, MCP server or hosted account. CLI/Skill are the supported entry
points in this version; a future MCP adapter must use this same contract.

Resolve the user's configured repository first. Below, `<repo>` means that
repository and `<project>` is the project relevant to the current task. Keep
these values explicit; never guess a private repository location.

```bash
python3 <repo>/scripts/cairn.py --repository <repo> projects
python3 <repo>/scripts/cairn.py --repository <repo> status --project <project>
python3 <repo>/scripts/cairn.py --repository <repo> brief --project <project> --thread <thread> --focus pricing --focus credits > previous-brief.json
python3 <repo>/scripts/cairn.py --repository <repo> brief-check --project <project> --thread <thread> < previous-brief.json
python3 <repo>/scripts/cairn.py --repository <repo> list --project <project>
python3 <repo>/scripts/cairn.py --repository <repo> get --project <project> --id <decision-id>
```

Without `--repository`, configuration uses `CAIRN_CONFIG`, then
`CAIRN_CONFIG_ROOT/config.json`, then `~/.cairn/config.json`. It must contain
`repository`, `identity`, and `default_project`. Unlike the legacy reader, the
new interface never falls back to the directory containing the script. The
configured default does not make an unrelated task belong to that project.

## Brief: thread-scoped recall candidates

`brief` requires an explicit project and a nonblank, opaque `--thread` of at
most 200 Unicode code points. The thread ID is compared as supplied and is
never used as a path. Provide 1–16 `--focus` occurrences, each 1–200 code
points after stripping surrounding whitespace. Duplicate terms are removed
using Unicode casefold, preserving the first spelling and order. `--limit`
defaults to 5 and accepts 1–50.

Only validated `valid` decisions can match. A term matches a literal casefolded
substring in the full ID, title, decision or scope, including Chinese phrases.
Any hit qualifies. Sort by number of distinct matched terms (descending),
number of distinct matched fields (descending), then ID (ascending). No dates
or semantic scores affect order. `relevance.matched_terms` follows focus order;
`matched_fields` follows ID, title, decision, scope order.

The [brief schema](../docs/schema/brief-output.schema.json) describes the
deterministic `schema:1` result with `kind:"cairn.hot-context"`, `brief_version:1`,
and `source_of_truth:false`. The host keeps this result short-term for its
thread. Cairn writes no brief file or cache. The example uses a file only to
illustrate passing the complete JSON back on stdin; use an ephemeral host
buffer or a private temporary file. Brief fields include:

- Project, thread, normalized focus, limit, a SHA-256 key of the resolved
  repository path (the path itself is not emitted), and the same project
  `snapshot` fingerprint as `list`.
- Items with ID, project, relative file, exact file revision, status, relevance,
  and bounded excerpts. Title and decision `headline` are at most 160 code
  points each; scope, exclusions and overturn conditions are at most 240 each.
  Each excerpt has a corresponding `*_truncated` flag. Missing text stays
  empty. There is no rationale, full Markdown body or timestamp.
- Selection counts `matched` before the limit and `returned` after it, with
  `truncated` when any matched candidate was omitted and
  `semantic_coverage:"unknown"`. `complete` only describes the source read,
  independently of matches and truncation. Even an empty brief retains all
  errors and warnings for the selected project.

### Validate a brief before reuse

`brief-check` requires the original full JSON on stdin and the expected
repository, project and thread on the command line or in configuration.
Unsupported schema/version, mismatched binding or invalid input is refused.
The supplied focus and limit must be valid and normalized; the host is
responsible for building a new brief when the task's focus or limit changes.

The CLI rebuilds the projection from the current L3 snapshot and returns
`freshness`, `reason`, `next_action`, and current `complete/errors/warnings`
without returning the old items:

- `fresh / unchanged` means the full projection agrees. The CLI returns
  `read_source` when candidates are absent, the source read is incomplete, the
  limit omits candidates, or any returned decision headline, scope, exclusion
  or overturn condition is truncated. A clipped title alone does not trigger
  fallback. Before relying on a candidate as a current constraint, use exact
  `get` to read any truncated decision text or applicability condition in full.
  Use the original text for the missing portion. Otherwise the CLI returns
  `use_brief`. Review warnings and assess applicability before using a brief.
- `stale / source_changed` means a different project fingerprint, even if only
  a non-matching record was added, edited or deleted. `stale / projection_changed`
  means the fingerprint agrees but the supplied projection differs.
  Both return `rebuild`; discard the old brief.
- A pending write returns `RECOVERY_REQUIRED`; a detected concurrent change
  returns `REVISION_CONFLICT`. Neither a refusal nor an unknown response may
  be reused. Freshness is a comparison of current file contents, not an
  audit log or an ability to retract text already injected into a conversation.

`brief` and `brief-check` read one project; they do not share state across
threads. Ordinary recall can use its brief, then fall back to L3 `list`/`get`.
Open exact source records directly for known IDs, original wording or reasons,
conflicts, high-impact verification and decision lifecycle changes.

## Read: navigate, then open an exact decision

`list` filters by project, `--status valid|superseded|revoked` (default `valid`),
and optional `--since YYYY-MM-DD`. It returns title, first 140 characters of the
decision, first 240 characters of scope, explicit truncation flags, relative
file path and SHA-256 revision. L3 `list` and `get` apply no relevance ranking. Unknown
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
