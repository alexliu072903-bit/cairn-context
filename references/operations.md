# Operate and recover Cairn

Use this route for interrupted writes, pending recovery, external-editor conflicts, optional synchronization or an installed repository that lacks current capabilities.

## Recovery

Follow the recovery section of [access.md](access.md). Check `status` before starting another write when a prior operation may have been interrupted.

- Resume the accepted request with `recover` or retry the identical write using the same request id.
- Do not delete journals, pending markers or create a new request id to escape recovery.
- `RECOVERY_CONFLICT` means an external change differs from both recorded states. Preserve it and report the conflicting path; do not overwrite it.
- A receipt proves completion of that operation, not that the record is still the latest state. Read back current records.

Journals contain private before/after snapshots and request sources. Keep them in the configured private repository.

## External edits and concurrency

Cairn's lock coordinates Cairn writers, not arbitrary editors or Git operations. Avoid checkout, rebase and legacy scheduled sync during a write or pending recovery. Manual Markdown edits remain supported and are validated on the next read.

Do not infer that an I/O failure means nothing changed. Inspect status and the transaction phase before retrying.

## Synchronization

Synchronization is an optional repository capability. Enable or alter it only when the user explicitly asks.

Before enabling `scripts/setup-autosync.sh`, verify that the repository is Git-backed, has an accessible intended remote branch and is meant to contain the user's private context. Never create a public context repository or change visibility without explicit authorization.

On sync failure or conflict, preserve local commits and both sides of the conflict. Report the repository's sync log location; do not discard or overwrite history. An ordinary decision write does not force an immediate commit or push.

## Capability upgrades

When the installed repository lacks the unified reader or writer, state the concrete missing guarantee. Use the public installer `upgrade` path only when the user asks to upgrade; it refreshes managed scripts and installed Skill files while preserving decisions and project files.
