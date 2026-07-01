---
name: history-surfer
description: Use when the user wants to recall, search, or reference their own PAST Claude Code prompts (across this or other projects) — e.g. "what did I ask about X earlier", "find my previous prompt about Y", "show my prompt history", "have I mentioned Z before", "what was that prompt where I pasted the screenshot". Queries the local prompt log via the `surfer` CLI. Do NOT use for searching code or files.
---

# Surfing prompt history

The user keeps a local, searchable log of every prompt they've sent to Claude Code
(captured by claude-history-surfer). Answer questions about their past prompts by
running the `surfer` CLI and summarizing real results — never invent prompts.

## How to query

Run these with the Bash tool and read the JSON:

| Goal | Command |
|-|-|
| Search **current project** (default) | `surfer search "<query>" --json` |
| Recent prompts, **current project** (default) | `surfer list --limit 20 --json` |
| Search across **all** projects (only if asked) | `surfer search "<query>" --all --json` |
| Recent across **all** projects (only if asked) | `surfer list --all --limit 20 --json` |
| Full detail + attachments | `surfer show <id> --json` |
| Only favorites / a tag | add `--favorites` or `--tag <tag>` |
| Regex search | add `--regex` |

Each result object has: `id` (`session:seq`), `ts`, `cwd`, `prompt`, `tags`,
`favorite`, and `attachments` (each with `kind`, `stored` path, `bytes`).

## Guidance
- **Default to the CURRENT project.** `surfer` scopes to the project you're in
  (the session's working directory) unless you pass `--all`. Only add `--all`
  when the user explicitly asks about *other* projects, *all/any* projects, or
  "across projects." Never add `--all` by default.
- Prefer `--json`, then summarize concisely (id, date, project, a snippet).
- Use `surfer show <id>` to pull the full text or attachment paths for one prompt.
- If `surfer` is not found, tell the user to install claude-history-surfer
  (`curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash`).
- The user can also browse interactively with `surfer tui`.
