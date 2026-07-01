# claude-history-surfer

Easily navigate your Claude Code prompt history.

`claude-history-surfer` keeps a durable, searchable log of **every prompt you send
to Claude Code**, across **all your projects** — including the **files, pasted
images, and large pasted text** you attach — and lets you search, browse, and
curate that history from the terminal or from inside any Claude Code session.

It captures prompts with a [Claude Code hook](https://docs.claude.com/en/docs/claude-code/hooks),
stores everything **locally** (nothing is ever uploaded), and gives you a CLI, an
interactive TUI, a `/history` slash command, and a `history-surfer` skill.

---

## Why

Claude Code already records prompts in `~/.claude/history.jsonl` and full
transcripts under `~/.claude/projects/`, but that data is a flat, internal,
per-session dump — not something you can search per-project, that captures your
attachments, or that you can browse and curate. This tool builds that layer on
top (and seeds itself from your existing history so nothing is lost).

## Install

One line — no manual clone required:

```bash
curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash
```

Seed your existing prompts at install time by passing `--import-history`:

```bash
curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash -s -- --import-history
```

Or from a clone:

```bash
git clone https://github.com/ContextLab/claude-history-surfer.git
cd claude-history-surfer
./install.sh                 # add --import-history to seed past prompts
```

The installer:

- symlinks the `surfer` CLI into `~/.local/bin`,
- adds `UserPromptSubmit` + `Stop` hooks to `~/.claude/settings.json`
  (**backing it up first** and preserving every other setting),
- installs the `history-surfer` skill and `/history` command into `~/.claude`,
- creates the local data directory `~/.claude/history-surfer/`.

**After installing, restart Claude Code** — hooks load at startup, so capture
begins in your next session. Make sure `~/.local/bin` is on your `PATH`.

Requirements: `python3` (standard library only — no pip packages) on macOS or
Linux, and `git` for the one-line install.

## Quick start

```bash
surfer import-history          # seed from ~/.claude/history.jsonl (one-time, idempotent)
surfer list --all              # most recent prompts across all projects
surfer search "vector" --all   # full-text search
surfer tui                     # interactive browser
```

Inside a Claude Code session you can also just ask — the `history-surfer` skill
runs `surfer` for you — or type `/history <query>`.

## What gets captured

For every prompt, in the project you sent it from:

- the full prompt text (including slash commands — nothing is filtered out),
- **`@file` references** — snapshotted as-sent (content-addressed, so an edit
  later doesn't change what you sent),
- **pasted images** — extracted from the transcript and saved as real image files,
- **large pasted text** — captured in full (blobbed to a file when very large).

Capture is best-effort and completely non-blocking: the hook always exits cleanly
and never writes to your session, so it can't interfere with a prompt.

## CLI reference

Scope defaults to the **current project**; add `--all` for every project, or
`--project <path>` for a specific one.

| Command | What it does |
|-|-|
| `surfer search <query> [--all] [--regex] [--favorites] [--tag T] [--since YYYY-MM-DD] [--limit N] [--json]` | Search prompt text (and tags) |
| `surfer list [--all] [--favorites] [--tag T] [--limit N] [--json]` | Most recent prompts |
| `surfer show <id> [--json]` | Full prompt + attachment paths (`id` = `session:seq`, prefix ok) |
| `surfer stats` | Prompt counts per project |
| `surfer import-history` | Seed from `~/.claude/history.jsonl` (idempotent) |
| `surfer tag <id> <tag>` / `surfer untag <id> <tag>` | Add / remove a tag |
| `surfer favorite <id>` / `surfer unfavorite <id>` | Star / unstar |
| `surfer edit <id> [--text "..."]` | Edit prompt text (original is preserved) |
| `surfer delete <id>` / `surfer restore <id>` | Soft-delete / restore |
| `surfer open <id> [--reveal]` | Print (or open, on macOS) attachment paths |
| `surfer tui [--all]` | Launch the interactive browser |

Examples:

```bash
surfer search "race condition" --all --since 2026-01-01
surfer show 3f7b0a97:23
surfer favorite 3f7b0a97:23
surfer tag 3f7b0a97:23 graphics
surfer list --all --favorites
```

Curation (tags, favorites, edits, deletes) is stored in a separate append-only
overlay — your captured prompts are **never mutated in place**, and edits keep
the original text.

## TUI

`surfer tui` opens an interactive browser:

| Key | Action |
|-|-|
| `↑`/`k` `↓`/`j` | Move |
| `enter` | Detail view / back |
| `/` | Filter (search) |
| `f` | Toggle favorite |
| `t` | Add a tag |
| `e` | Edit in `$EDITOR` |
| `d` / `u` | Delete / restore |
| `o` | Open attachments |
| `a` | Toggle current-project ↔ all-projects |
| `D` | Show / hide deleted |
| `q` | Quit / back |

## In-session recall (skill + slash command)

- **Skill `history-surfer`** — when you ask things like *"what did I ask about the
  vector field earlier?"* or *"find my previous prompt where I pasted that
  screenshot"*, Claude runs `surfer` and summarizes the results.
- **`/history <query>`** — a direct slash command that searches your history.

## Storage & privacy

All data is **local** under `~/.claude/history-surfer/` and is **never uploaded**
or committed (the repo's `.gitignore` excludes data). Layout:

```
~/.claude/history-surfer/
  projects/<project-slug>/
    prompts.jsonl                 # one record per prompt
    attachments.jsonl             # attachment records
    attachments/<sha256>.<ext>    # content-addressed files/images/text blobs
    overlay.jsonl                 # your tags/favorites/edits/deletes
  state/<session_id>.json         # per-session seq + transcript offset
  meta/errors.log
```

Your prompts can contain secrets you pasted. The store is local-only, but treat
it accordingly. To purge everything:

```bash
rm -rf ~/.claude/history-surfer
```

Override the data location with `CLAUDE_HISTORY_SURFER_DIR`, and the max
attachment size with `CLAUDE_HISTORY_SURFER_MAX_ATTACH` (bytes).

## Uninstall

```bash
./uninstall.sh
# or:  curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/uninstall.sh | bash
```

This removes the hooks (backing up `settings.json` again), removes the symlinks,
and **leaves your captured prompt data intact**. Delete the data yourself with
`rm -rf ~/.claude/history-surfer` if you want it gone.

## Development

Pure Python standard library. Run the test suite (real tests — real files, real
transcripts, a real pty for the TUI, real subprocess for the hooks; no mocks):

```bash
./run_tests.sh
```

See [`docs/design.md`](docs/design.md) for the architecture.

## License

MIT — see [LICENSE](LICENSE).
