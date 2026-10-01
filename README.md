# Cairn Context

**English | [中文](README.zh-CN.md)**

A Skill that lets a new agent session find the project decisions that are already confirmed and relevant to the task, so you stop re-explaining them.

It works with Claude Code, Codex, and any agent that loads a `SKILL.md`. Your decisions live in a repository you own; this public repository holds only the Skill, an installer, and a template.

## What it does

- Reads only the decisions that bear on the current task. The agent picks them by file name and title (see Limitations).
- Tells a confirmed decision apart from an inclination, an open question, and a temporary experiment. If the signal is unclear, it asks once.
- Keeps history when a decision changes. The old file stays, and a `supersedes` link points from the new one to it.
- Logs your corrections, so a wrong judgment can be traced.

These are instructions to the agent, not enforced guarantees. How well they hold depends on the model's instruction following.

## Install

Clone this repository, then run the installer with the agent you use.

For Claude Code:

```bash
bash install.sh --identity "Your Name" --project "your-project" --repository "$HOME/cairn" --claude-code
```

For Codex:

```bash
bash install.sh --identity "Your Name" --project "your-project" --repository "$HOME/cairn" --codex
```

For both, pass both flags. For any other agent, point at its skills directory:

```bash
bash install.sh --identity "Your Name" --project "your-project" --repository "$HOME/cairn" --skills-dir "/path/to/skills"
```

Without a target flag the installer installs to Codex, as earlier versions did.

The installer:

1. creates a local Cairn repository from `template/`;
2. writes `~/.cairn/config.json`;
3. installs the Skill to each target. Codex also gets `agents/openai.yaml`.

It refuses to overwrite a non-empty repository or an existing Skill, and it checks every target before it writes anything.

## Limitations

- **Retrieval is by index, not search.** The agent reads a one-line summary of every valid decision and chooses which to open. There is no keyword search, embedding, or ranking, and the agent's choice is a judgment, not a guarantee.
- **No learning.** Corrections are appended to `protocol/benchmark/feedback.md`. Nothing reads that log to change later behavior.

## Roadmap

Not built yet, listed so you know what is missing:

- A keyword search command, for repositories with too many decisions to read as one index.
- A way to turn a repeated correction into a reviewed rule.

## Find decisions faster: the index

For each project the installer creates `projects/<project>/decisions-index.md`: one line per **valid** decision, newest first.

```text
- 2026-09-01 plain-markdown: Use plain Markdown — Decisions are stored as plain Markdown files.
```

Each line is `date id: title — first sentence of the decision`. The Skill reads this file first, then opens `decisions/<id>.md` only for the lines that matter to the task. Superseded and revoked decisions are not listed; they stay in `decisions/` as history.

The file is generated. Do not edit it. After you record or change a decision, refresh it:

```bash
python3 ~/cairn/scripts/index.py
```

The Skill does this itself after it records a decision. `index.py --check` exits with 1 when the index is missing or out of date, and `validate.py` warns about a stale index. The script uses only the standard library.

A repository created by an earlier version does not have `index.py`. Copy `template/scripts/index.py` (and the newer `validate.py`) into its `scripts/` directory, then run it once.

## Validate your decisions

Decision files are plain Markdown with a small frontmatter block. Check them with:

```bash
python3 ~/cairn/scripts/validate.py
```

It reads only the standard library, so there is nothing to install. It reports an error when:

- a required field is missing (`project`, `decision`, `status`, `decided_by`, `decided_at`), or `status` is not `valid`, `superseded`, or `revoked`;
- `decided_at` is not a real date in `YYYY-MM-DD` form;
- `project` or `decision` does not match where the file lives;
- `supersedes` (one id, or a list when a decision replaces several) points to a decision that does not exist, to itself, or in a loop;
- `superseded_by`, if you use it, points to a decision that does not exist;
- the decision it replaces is still marked `valid`.

It reports a warning, not an error, for:

- a missing section. English headings (`Decision`, `Rationale`, `Scope`, `Explicitly excluded`, `Overturn signal`) and Chinese headings (`结论`, `为什么`, `适用范围`, `明确不做`, `推翻条件`) are both recognized, and a file is checked against the set it uses;
- an unknown field, or an unusual id;
- a `superseded` decision that nothing replaces;
- one decision replaced by several (a split), or a `superseded_by` whose target does not list it in `supersedes`.

Options: `--json` for machine-readable output, `--strict` to fail on warnings. The exit code is 0 when there are no errors, 1 when there are, and 2 when the repository cannot be read. The Skill runs it after recording a decision if the script is present.

A repository created by an earlier version does not have the script. Copy `template/scripts/validate.py` from this repository into its `scripts/` directory.

To run this project's own tests: `python3 -m unittest discover -s tests`.

## Optional 30-minute Git sync

The generated Cairn repository includes an optional macOS LaunchAgent. Every 30 minutes it commits local changes, rebases onto the remote branch, and pushes. A conflict stops the sync and keeps the local commit for you to resolve.

First create a **private** GitHub repository and push the generated Cairn repository:

```bash
cd "$HOME/cairn"
git init -b main
git add .
git commit -m "init: create Cairn context"
gh repo create YOUR_ACCOUNT/cairn --private --source . --remote origin --push
```

Then enable autosync yourself:

```bash
bash "$HOME/cairn/scripts/setup-autosync.sh"
```

The Skill installer never enables autosync. When the GitHub CLI is available, setup refuses to sync to a repository that is public.

## Repository layout

```text
~/cairn/
├── AGENTS.md
├── CLAUDE.md              imports AGENTS.md
├── protocol/
│   ├── README.md
│   └── benchmark/
│       ├── feedback.md
│       └── cases.yaml
├── scripts/
│   ├── setup-autosync.sh
│   ├── sync.sh
│   ├── validate.py
│   └── index.py
└── projects/
    └── your-project/
        ├── README.md
        ├── state.md
        ├── decisions-index.md   generated
        └── decisions/
```

## Related projects

| Project | Where the context lives | Pick it when |
| --- | --- | --- |
| **Cairn Context** (this one) | A separate repository you own, for one or several projects | You want decisions kept outside the project repository, and an agent that judges when to read or record |
| [Shared Project Context](https://github.com/alexliu072903-bit/shared-project-context) | A workspace that tracks goals and evidence across people and agents | You need to keep several actors aligned with goals someone set |

[Cairn Lite](https://github.com/alexliu072903-bit/cairn-lite), an earlier project that kept the context inside the project folder, is archived and no longer maintained.

## Privacy boundary

Do not point several people at one personal Cairn repository just to share the Skill. Share this public Skill and keep each person's context repository private. Create a separate team repository only for decisions that are meant to be read by the team.

## License

MIT
