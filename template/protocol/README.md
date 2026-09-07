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

## Correction

Correct repository facts first. Do not change this protocol from a single correction. Add a feedback or benchmark system only when the team explicitly decides it needs one.
