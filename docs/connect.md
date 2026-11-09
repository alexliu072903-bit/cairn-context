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
5. Run the installed `scripts/cairn.py status --project <id>`, then `list`.
   If records exist, use `get` on one exact id and verify its source and scope.
   If empty and complete, report "connected, no decisions yet"; do not invent a
   record or perform a test write into personal data.
6. Report the actual project, read result, warnings and supported commands.
   Describe writes as available through the writer, **not runtime-verified**
   unless an authorized real write was performed. Return to the original task.

See [the unified access contract](../references/access.md) for navigation,
writes and recovery. No MCP server is shipped in this iteration; Skill and CLI
use the same implementation. Remote-only Agents need access to the configured
repository/runtime; copying a prompt alone does not provide that access.
