---
description: Search your Claude Code prompt history (claude-history-surfer)
argument-hint: [search query]
allowed-tools: Bash(surfer:*)
---

Search my past Claude Code prompts.

These default to the **current project** (the session's working directory):

- If `$ARGUMENTS` is non-empty, run: `surfer search "$ARGUMENTS" --limit 30`
- If it is empty, run: `surfer list --limit 30`

Only add `--all` (e.g. `surfer search "$ARGUMENTS" --all`) if I explicitly ask
about other projects or across all projects.

Then present the matching prompts as a short list — id, date, project, and a
one-line snippet each. If I ask about a specific one, use `surfer show <id>` for
the full text and attachment paths. Only report what `surfer` actually returns.
