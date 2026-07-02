# 🏄 claude-history-surfer

**Search, browse, export, and replay every prompt you've ever sent to Claude Code.**

`claude-history-surfer` keeps a durable, searchable log of **every prompt you send
to Claude Code**, across **all your projects** — including the **files, pasted
images, and large pasted text** you attach. It gives you an intuitive way to find
that one prompt from last week, reuse the wording that worked, export a project's
prompt history to share, and even *replay* a saved sequence of prompts into a
fresh Claude Code session.

It captures prompts with a [Claude Code hook](https://docs.claude.com/en/docs/claude-code/hooks),
stores everything **locally** (nothing is ever uploaded), and gives you a CLI, an
interactive TUI, a `/history` slash command, and a `history-surfer` skill.

![TUI demo — browse, live-filter, and star prompts](docs/media/tui.gif)

---

## Why

Your prompts are a record of how you actually work — the phrasings, the setup
sequences, the hard-won wording that finally got Claude to do the right thing.
But that record is normally write-only: once a prompt scrolls off screen it's
effectively gone. Claude Code *does* keep raw data in `~/.claude/history.jsonl`
and full transcripts under `~/.claude/projects/`, but that's a flat, internal,
per-session dump — you can't search it per project, it drops your attachments,
and you can't browse or curate it.

`claude-history-surfer` turns that raw data into an **intuitive, searchable
interface to your own past prompts**, so you can:

- **Reuse** what worked — pull up the exact prompt (or whole sequence of prompts)
  that set up a project, fixed a class of bug, or produced a good result, and run
  it again somewhere new.
- **Reference** what you asked — "what was that prompt where I pasted the
  screenshot?", "how did I phrase the migration request last month?" — and get the
  real text back, attachments included.
- **Share** a project's prompt history as a clean Markdown or JSON file.
- **Replay** a saved prompt sequence into a fresh session, one prompt at a time.

It seeds itself from your existing history on install, so nothing is lost.

## Install

One line — no manual clone required. The default seeds your existing prompts so
your whole history is searchable immediately:

```bash
curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash -s -- --import-history
```

Prefer a clean install (start fresh, capture only new prompts)? Drop the flag:

```bash
curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash
```

Or from a clone:

```bash
git clone https://github.com/ContextLab/claude-history-surfer.git
cd claude-history-surfer
./install.sh --import-history      # omit the flag for a clean install
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
surfer list --all              # most recent prompts across all projects
surfer search "vector" --all   # full-text search
surfer tui                     # interactive browser
surfer export --all -o my-prompts.md   # export to a shareable Markdown file
```

Inside a Claude Code session you can also just ask — the `history-surfer` skill
runs `surfer` for you — or type `/history <query>`. Both default to your
**current project**; add `--all` (or say "across all projects") to search
everywhere.

## What gets captured

For every prompt, in the project you sent it from:

- the full prompt text (including slash commands you run),
- **`@file` references** — snapshotted as-sent (content-addressed, so an edit
  later doesn't change what you sent),
- **pasted images** — extracted from the transcript and saved as real image files,
- **large pasted text** — captured in full (blobbed to a file when very large).

Harness-injected notifications and command echoes (background task
notifications, IDE file-open events, slash-command XML expansions, and the
like) are filtered out by default — only prompts you actually wrote are shown.
(Noise entries recorded before this filtering existed stay on disk and remain
recoverable via the store's `include_noise=True` option; new ones are simply
not recorded.)

Capture is best-effort and completely non-blocking: the hook always exits cleanly
and never writes to your session, so it can't interfere with a prompt.

## CLI reference

Scope defaults to the **current project** everywhere (search, list, show, stats,
export); add `--all` for every project, or `--project <path>` for a specific one.

![CLI demo — list, search, show](docs/media/cli.gif)

| Command | What it does |
|-|-|
| `surfer search <query> [--all] [--regex] [--favorites] [--tag T] [--since YYYY-MM-DD] [--limit N] [--json]` | Search prompt text (and tags) |
| `surfer list [--all] [--favorites] [--tag T] [--limit N] [--json]` | Most recent prompts (`--limit 0` = full history, no recency cap) |
| `surfer show <id> [--json]` | Full prompt + attachment paths (`id` = `session:seq`, prefix ok) |
| `surfer export [query] [--all] [--favorites] [--tag T] [--since D] [--format md\|json] [-o FILE]` | Export prompts to Markdown/JSON |
| `surfer replay <file> [--select S] [--first N] [--last N] [--dry-run] [--model M] [--session-id U] [-o FILE]` | Replay an export into a session |
| `surfer stats [--all] [--project P]` | Prompt counts, favorites/attachments, and oldest..newest date span per project (current project by default) |
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
surfer list --limit 0                  # full history, current project
surfer stats --all                     # counts + date span, every project
```

`surfer stats --all` output looks like:

```
   142  2026-01-05..2026-06-21  -Users-surfer-projects-aurora  (12 ★, 3 📎)
    37  2026-04-02..2026-06-19  -Users-surfer-projects-tide  (2 ★, 0 📎)
```

Curation (tags, favorites, edits, deletes) is stored in a separate append-only
overlay — your captured prompts are **never mutated in place**, and edits keep
the original text.

## Export

Turn any slice of your history into a shareable file — **Markdown** (default,
great for reading and sharing) or **JSON** (exact, machine-readable). Export
reuses the same scope and filters as `search`/`list`, so you export exactly the
subset you can already find:

```bash
surfer export                                   # current project → Markdown (stdout)
surfer export --all -o my-prompts.md            # every project → a file
surfer export --favorites --format json -o faves.json
surfer export "vector" --tag graphics --since 2026-01-01 -o graphics.md
```

The Markdown format is human-readable **and** re-importable: each prompt is
wrapped in invisible HTML-comment markers, so `surfer replay` can read the exact
prompts back (even prompts that contain their own code fences). JSON carries the
same prompts plus export metadata and attachment info.

![export + replay demo](docs/media/export-replay.gif)

## Replay

Play the prompts from an export back into a **fresh Claude Code session**, one at
a time — waiting for each response before sending the next, so context builds up
like a real conversation. Replay drives your installed `claude` CLI, so it runs
in real Claude Code with your tools and settings.

```bash
surfer replay my-prompts.json                   # replay everything, in order
surfer replay my-prompts.md --select "0,3-7,10-"  # a subset
surfer replay my-prompts.json --first 5         # just the first 5
surfer replay my-prompts.json --last 3          # just the last 3
surfer replay my-prompts.json --dry-run         # preview — spends no tokens
```

**Selecting prompts.** `--select` takes a comma-separated list where **the order
you write is the order they run**:

| Token | Means |
|-|-|
| `0` | prompt at index 0 |
| `3-7` | prompts 3 through 7 (inclusive) |
| `10-` | prompt 10 through the end |
| `-4` | the start through prompt 4 |

Indices are 0-based (the numbers shown by `surfer export`). Duplicates re-run a
prompt; out-of-range indices print a warning and are skipped. `--first N` and
`--last N` are shortcuts. Add `-o transcript.md` to save the prompt/response
exchange, `--model <model>` to pick the model, and `--session-id <uuid>` to
name (or resume) the session instead of generating a fresh one.

> **Note (v1):** replay sends prompt **text** as it was originally sent. `@file`
> references re-resolve live if those files still exist; pasted images and large
> text blobs are not re-attached.

## TUI

`surfer tui` opens an interactive browser (shown at the top of this page):

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

`surfer tui` defaults to the **current project**, same as the CLI; pass `--all`
(or press `a` inside the TUI) to browse every project.

## In-session recall (skill + slash command)

- **Skill `history-surfer`** — when you ask things like *"what did I ask about the
  vector field earlier?"* or *"find my previous prompt where I pasted that
  screenshot"*, Claude runs `surfer` and summarizes the results. Defaults to
  your current project; say "across all projects" (or similar) to search
  everywhere.
- **`/history <query>`** — a direct slash command that searches your history,
  scoped to the current project by default.

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
it accordingly. Exports are plain files — mind what you share. To purge
everything:

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

See [`docs/design.md`](docs/design.md) for the architecture, and
[`dev/README.md`](dev/README.md) for developer tooling — running tests, the
demo-store seeder, and how the screenshots/GIFs above are generated (with `vhs`,
a developer-only dependency that the user installer never touches).

## License

MIT — see [LICENSE](LICENSE).
