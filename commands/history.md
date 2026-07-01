---
description: Search your Claude Code prompt history (claude-history-surfer)
argument-hint: [search query]
allowed-tools: Bash(surfer:*)
---

Search my past Claude Code prompts.

- If `$ARGUMENTS` is non-empty, run: `surfer search "$ARGUMENTS" --all --limit 30`
- If it is empty, run: `surfer list --all --limit 30`

Then present the matching prompts as a short list — id, date, project, and a
one-line snippet each. If I ask about a specific one, use `surfer show <id>` for
the full text and attachment paths. Only report what `surfer` actually returns.
