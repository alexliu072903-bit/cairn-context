# Record durable decisions

Use this route only when the user clearly commits to execution, rejects a direction, replaces or revokes a prior decision, directly requests capture, or corrects an existing Cairn record.

## Classify before writing

Do not record tentative preferences, open comparisons, ordinary implementation steps, temporary experiments or the Agent's recommendation. If durable intent or project scope is genuinely ambiguous, ask once. No explicit confirmation means no write.

Read the current L3 records on the same subject and scope first. For correction, revocation or replacement, use exact `get` directly. Reuse an existing record when the confirmed conclusion is unchanged. New evidence for the same conclusion is not automatically a new decision. Similar titles or a newer timestamp do not prove replacement.

## Select the lifecycle action

- `create`: a new confirmed decision with no predecessor.
- `supersede`: a confirmed replacement for one or more current decisions.
- `revoke`: withdrawal of an existing current decision without a replacement.
- `correct`: repair of an inaccurate Cairn record while preserving its lifecycle. A changed product choice uses supersede or revoke.

Read `<repository>/protocol/README.md` before composing content. Preserve attribution and history. Do not invent rationale, scope, exclusions or overturn signals; use the Protocol's unknown value when information is absent. Do not create a project unless the Protocol and user authorize it.

## Write through the unified contract

When `scripts/cairn.py` exists, follow the write section of [access.md](access.md):

1. Read every affected record and retain its revision.
2. Build one complete request with explicit user intent/source, expected revisions and a stable request id.
3. Supply user-authored text through a JSON file or process pipe, not shell interpolation.
4. Run `write`; do not bypass refusals by editing files directly.
5. Read back every affected record and verify its status, history links and conclusion.
6. Discard previous briefs for the affected project after a successful write and read-back. If recovery is needed, do not reuse them. Text already present in L1 cannot be retracted by Cairn; tell the current thread which decision has changed before using it again.

`confirmed:true` is the Agent's assertion that the user intent was explicit; the CLI does not make that judgment. Retry the identical request with the same request id. A new id is not a recovery mechanism.

The `correct` action records the original and corrected record plus the supplied correction source once. Include the relevant user correction in that source and do not append the same event separately.

## Legacy repositories

If the unified writer is absent, follow the installed Protocol's direct-file workflow and disclose the missing versioned-write and recovery guarantees. After writing, run the repository validator and indexer when present. Fix validation errors caused by the new record before reporting success.

Decision capture never includes source code, product documents, design files or full conversation logs. A bounded source reference is enough.
