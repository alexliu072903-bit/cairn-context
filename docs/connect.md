# Connect an Agent to Cairn

Copy this into an Agent that can read local files and run Python:

> Please connect Cairn Context using the official repository's `docs/connect.md`:
> https://github.com/alexliu072903-bit/cairn-context
> First check whether Cairn is already configured. Reuse my repository and
> customized Skill; do not reinstall over them. If this is a first installation,
> ask only for my identity, project and private repository location if they are
> not already specified. Verify that the project index and a real decision can
> be read, report the available capabilities, then return to my original task.
> Keep Cairn's confirmed-decision rules. Do not install Basic Memory or enable
> Git synchronization as part of connecting.

## Agent procedure

1. Read the existing configuration using `CAIRN_CONFIG`, then
   `CAIRN_CONFIG_ROOT/config.json`, then `~/.cairn/config.json`. Do not infer a
   repository or identity from unrelated context.
2. From a trusted source checkout, run `python3 install.py status --json`.
   Inspect `state`, `validation`, `stale_indexes`, `upgrade_available` and the
   host's installed Skill. `ready` alone is not successful validation.
3. If already installed, preserve decisions, configuration and customized
   Protocol/Skill. Preview `python3 install.py upgrade --dry-run --json`.
   An authorized upgrade without host flags updates managed scripts only;
   no host flags means no replacement of a customized Skill. Add the unified
   access workflow to that customized Skill only when authorized, preserving
   its stronger decision rules. The current source contains the reference at
   `references/access.md`.
4. For a new installation, obtain the identity, applicable project and private
   repository path, then use the README's installer command for the requested
   host. This is local setup, not a hosted connection; a prompt does not bypass
   the host's filesystem or execution permissions.
5. Run the installed `scripts/cairn.py status --project <id>` to see its
   capabilities. If it advertises `brief` and `brief-check`, use a literal term
   from the task and this thread's opaque ID to build a brief and check its full
   output. The host keeps it only for this project and thread. Use `list` to
   verify project contents, then `get` on one exact ID to verify source and
   scope if records exist. Report "connected, no decisions yet" only if
   `list` is empty and complete; a brief with no matches is insufficient.
   Do not perform a test write into personal data.
6. Report the actual project, read result, warnings and supported commands.
   Describe writes as available through the writer, **not runtime-verified**
   unless an authorized real write was performed. Return to the original task.

For ordinary recall, use the host's current context (L1), then its
thread brief (L2), then the configured repository (L3) if the candidates are
insufficient. L3 is authoritative; known IDs and high-impact or lifecycle
checks go straight there. Older CLI versions can use `list` and `get`
without a brief. See [the unified access contract](../references/access.md)
for the exact commands, writes and recovery. No MCP server is shipped in this iteration; Skill and CLI
use the same implementation. Remote-only Agents need access to the configured
repository/runtime; copying a prompt alone does not provide that access.
