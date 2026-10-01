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

- **No retrieval.** The agent chooses which decision files to read by scanning names and titles. There is no search index, embedding, or ranking.
- **No learning.** Corrections are appended to `protocol/benchmark/feedback.md`. Nothing reads that log to change later behavior.

## Roadmap

Not built yet, listed so you know what is missing:

- A small index that lets the agent find decisions without scanning every title.
- A way to turn a repeated correction into a reviewed rule.

## Validate your decisions

Decision files are plain Markdown with a small frontmatter block. Check them with:

```bash
python3 ~/cairn/scripts/validate.py
```

It reads only the standard library, so there is nothing to install. It reports an error when:

- a required field is missing (`project`, `decision`, `status`, `decided_by`, `decided_at`), or `status` is not `valid`, `superseded`, or `revoked`;
- `decided_at` is not a real date in `YYYY-MM-DD` form;
- `project` or `decision` does not match where the file lives;
- `supersedes` points to a decision that does not exist, to itself, or in a loop;
- the decision it replaces is still marked `valid`, or more than one decision replaces the same one.

It reports a warning, not an error, for a missing section, an unknown field, an unusual id, or a `superseded` decision that nothing replaces.

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
│   └── validate.py
└── projects/
    └── your-project/
        ├── README.md
        ├── state.md
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
