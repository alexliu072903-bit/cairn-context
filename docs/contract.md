# Integration contract

Cairn's data is plain files in a repository the user owns. This page defines how
another program (an app, a web service, a script) reads that data and checks the
installation state without re-deriving the rules.

There is one reference implementation, written in Python's standard library. An
integration either calls it or re-implements it and proves it agrees with the
conformance cases.

## What an integration may rely on

| Need | Use | Output |
| --- | --- | --- |
| Read decisions | `scripts/read.py` in the repository | [`read-output.schema.json`](schema/read-output.schema.json) |
| Is Cairn enabled, and what is wrong | `install.py status --json` | [`status-output.schema.json`](schema/status-output.schema.json) |
| Create a repository and install the Skill | `install.py install --json` | `{ok, actions, ...}` or `{ok:false, code, error}` |
| Refresh scripts and the installed Skill | `install.py upgrade --json` | same shape |
| Check another implementation | `tests/conformance/` | see below |

Both scripts accept `--dry-run` where they write (`install`, `upgrade`).
Install and upgrade exit `0` on success (including a successful dry run), `1`
on a refusal or I/O failure. Invalid command-line arguments exit `2` and print
usage to stderr rather than JSON.

## Decision file

`projects/<project>/decisions/<id>.md`: YAML-like frontmatter, then Markdown.

- Required frontmatter: `project`, `decision`, `status`, `decided_by`, `decided_at`.
- `status` is `valid`, `superseded` or `revoked`.
- `decided_at` is `YYYY-MM-DD`. A timestamp is accepted by the reader, reduced to
  the date as written (no timezone conversion), and reported as a warning.
- `supersedes` and `superseded_by` are an id or a list of ids.
- Section titles come in two sets, one per file: `Decision`, `Rationale`, `Scope`,
  `Explicitly excluded`, `Overturn signal`, or `结论`, `为什么`, `适用范围`,
  `明确不做`, `推翻条件`. The reader maps both to the keys `decision`, `rationale`,
  `scope`, `excluded`, `overturn`; a missing section is the empty string.

The reader uses the single-file and history checks in `validate.py`; it omits
files with errors, including dangling history links and every member of a cycle.
Warnings do not exclude a file. Timestamp normalization happens before those
checks. Repository housekeeping checks (README, state and generated indexes)
are reported by `status`, not by the decision reader.

## `read.py`

```bash
python3 scripts/read.py [REPOSITORY] [--project ID ...] [--since YYYY-MM-DD] [--status valid,superseded,revoked]
```

- Output is ASCII-escaped JSON on stdout, independent of the pipe's locale;
  JSON decoding restores Unicode text. All success and repository-error
  responses conform to the published read schema.
- Tool-generated paths (`file` and diagnostic `path`) are relative to the
  repository, with `/` separators. Diagnostics omit raw input values and OS
  exception details. The reader rejects symbolic links and redirected directories
  below the selected repository instead of following them.
- Authored titles, sections, authors and history ids are preserved. They may
  themselves contain paths or references; review that content before sharing.
- Decisions are ordered newest `decided_at` first, then by id.
- Projects whose name starts with `_` are skipped. `--project` accepts lowercase
  ids containing letters, digits or hyphens.
- With `--project`, only those directories are read and listed. It never reads
  another project's decisions through a link. Explicit references written into
  the selected project's own content are not redacted.
- Dates, including `--since`, must be zero-padded `YYYY-MM-DD`. Full selected-project
  history is checked before filtering; diagnostics may refer to files outside
  the date/status window.
- Exit status: `0` success (file-level problems are in `errors`/`warnings`),
  `1` a requested project does not exist, `2` the repository cannot be read.
  `ok` reflects repository/project selection, not file quality; inspect `errors`.
  Invalid CLI arguments also exit `2`, with usage on stderr and no JSON response.

### Exporting a project

`--project <id> --since <date>` is the unit of sharing: the content of one
project from one date on. The resulting JSON can be consumed without repository access. The reader excludes
other project directories, `state.md` and the correction log. Sharing permission
and any references authored into the selected content remain the host's concern.

## `install.py status`

`state` is one of:

| state | meaning |
| --- | --- |
| `not_enabled` | no configuration file was found and no explicit repository was supplied |
| `error` | the configuration is invalid, the repository or default project is missing; see `reasons` |
| `ready` | readable; `validation` and `stale_indexes` still report quality problems |

Other fields: `upgrade_available` (the protocol version is lower than the tool's,
or a managed script differs), `hosts` (per skills directory: whether the host
looks configured and the Skill is installed).

Configuration lives at `$CAIRN_CONFIG`, else `$CAIRN_CONFIG_ROOT/config.json`,
else `~/.cairn/config.json`. `~` expands in both overrides. The installer,
reader, indexer and validator share this resolver. Readers without a repository
argument use the configured repository, then fall back to the repository that
contains the script if configuration is absent or invalid.

`status` exits `0` after reporting its state, including `error` and
`not_enabled`; integrations must inspect `state`. Supplying `--repository`
allows inspection without a configuration. It does not hide invalid configuration.
An I/O failure that prevents a status response exits `1` with `{ok:false, code,
error}` when `--json` is supplied.

## Versions

`protocol/VERSION` holds the repository's protocol version. A repository without
the file is version 0. `upgrade` updates only `scripts/index.py`,
`scripts/validate.py`, `scripts/read.py` and `protocol/VERSION`, plus an
installed Skill when it differs. It never edits decisions, project files, the
protocol text or the agent instruction files. All destinations are checked before
writing; linked files, redirected directories and hard-linked managed files are
refused with `code: "unsafe_path"`. Each updated file is replaced atomically.
Specify Skill targets explicitly (`--codex`, `--claude-code`, `--skills-dir`) or
use `--detect`; an omitted target list upgrades only repository files. A Codex
Skill includes both `SKILL.md` and `agents/openai.yaml`.

## Conformance cases

`tests/conformance/cases/*.json` each hold a repository under
`tests/conformance/repos/`, the arguments, the expected exit code and the
expected output. An implementation passes when, for every case:

1. it returns the same `projects`, `available_projects` and `ok`;
2. it returns the same errors and warnings, compared by `level` and `path`
   (message text is for people and may differ).

`tests/test_conformance.py` runs the reference reader against the cases.

The original 12 expectations were produced by the reference reader and manually
checked against their source files. The additional dangling-history,
noncanonical-date and unreadable-repository expectations were authored directly
from synthetic inputs, without generating them from reader output.
