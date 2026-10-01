# Cairn Decision Protocol

## Read

Before product or technical work that may depend on history, read the project overview, current state, and only the relevant valid decisions.

## Record

Record a decision when the user clearly confirms execution, rejects a direction, replaces or revokes an existing decision, or directly asks to record one.

Do not record tentative preferences, questions, ordinary tasks, temporary experiments, or the agent's own recommendation. If ambiguous, ask once whether the statement is an inclination or a confirmed decision. Without confirmation, do not write.

## Format

Write each decision to `projects/<project>/decisions/<decision-id>.md`:

```markdown
---
project: <project-id>
decision: <decision-id>
status: valid
decided_by: <identity>
decided_at: YYYY-MM-DD
supersedes: <optional previous decision-id>
---

# Title

## Decision

## Rationale

## Scope

## Explicitly excluded

## Overturn signal
```

Use only confirmed facts. Write `To be validated` when rationale, scope, or overturn signals were not provided.

## Change

Never overwrite history. Mark an old decision `superseded` or `revoked`, create a new decision when applicable, and connect it with `supersedes`.

## Validate

After writing or changing decisions, run:

```bash
python3 scripts/validate.py
```

It checks that each decision has the required fields and a valid status, that its `project` and `decision` match where the file is, that `supersedes` (one id or a list) points to existing decisions in the same project with no cycle, and that a decision replaced by another is no longer `valid`. Errors must be fixed. Warnings (missing sections, unknown fields, a split into several decisions, a superseded decision that nothing replaces) are advice.

## Index

`projects/<project>/decisions-index.md` lists every valid decision on one line (date, id, title, first sentence of the decision). It is generated; do not edit it. Read it first, then open only the decisions that matter. After recording or changing a decision, run:

```bash
python3 scripts/index.py
```

`python3 scripts/index.py --check` fails when the index is missing or out of date.

## Correction

When the user says an item was not a decision, was assigned to the wrong project, was inaccurate, or incorrectly superseded an older decision:

1. correct the repository fact first;
2. append the original context, Agent action, user correction, and correct behavior to `protocol/benchmark/feedback.md`;
3. do not change this protocol from one correction;
4. promote repeated or generalizable failures to `protocol/benchmark/cases.yaml` only when they justify a stable test.
