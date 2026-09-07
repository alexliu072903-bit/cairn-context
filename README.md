# Cairn Context

A small Codex Skill for keeping durable project decisions in a repository that you own and control.

The public repository contains only the reusable mechanism. Your identity, project context, decisions, corrections, and history live in a separate local or private repository.

## Install

Clone this repository, then run:

```bash
bash install.sh \
  --identity "Your Name" \
  --project "your-project" \
  --repository "$HOME/cairn"
```

The installer:

1. creates a private-by-default local Cairn repository from `template/`;
2. writes `~/.cairn/config.json`;
3. installs the Skill to `~/.codex/skills/cairn-context`.

It refuses to overwrite a non-empty repository or an existing Skill installation.

## Optional 30-minute Git sync

The generated Cairn repository includes an optional macOS LaunchAgent. It commits local changes, rebases onto the remote branch, and pushes every 30 minutes. Conflicts stop the sync and preserve the local commit for manual resolution.

First create a **private** GitHub repository and push the generated Cairn repository:

```bash
cd "$HOME/cairn"
git init -b main
git add .
git commit -m "init: create Cairn context"
gh repo create YOUR_ACCOUNT/cairn --private --source . --remote origin --push
```

Then explicitly enable autosync:

```bash
bash "$HOME/cairn/scripts/setup-autosync.sh"
```

Autosync is never enabled by the Skill installer. When GitHub CLI is available, setup refuses to sync to a repository reported as public.

## Repository layout

```text
~/cairn/
├── AGENTS.md
├── protocol/README.md
├── scripts/
│   ├── setup-autosync.sh
│   └── sync.sh
└── projects/
    └── your-project/
        ├── README.md
        ├── state.md
        └── decisions/
```

The Skill reads only context relevant to the current task and records only decisions the user has explicitly confirmed.

## Privacy boundary

Do not point multiple people at a personal Cairn repository merely to share the Skill. Share this public Skill; keep each person's context repository private. Create a separate team repository only for decisions that are intentionally team-readable.

## License

MIT
