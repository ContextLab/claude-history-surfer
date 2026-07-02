# claude-history-surfer — Design

_Last updated: 2026-06-30_

> Export/replay design detail: `docs/superpowers/specs/2026-07-01-export-replay-readme-design.md`.

## 1. Goal

Maintain a durable, searchable log of **every prompt** sent to Claude Code, across **all projects**, including **files, images, and large pasted text** the user attaches — and make past prompts **easy to recall, browse, curate, and edit** from inside any Claude Code session.

## 2. What Claude Code already provides (and why it isn't enough)

| Store | Contents | Gap |
|-|-|-|
| `~/.claude/history.jsonl` | One line per prompt, all projects: `{display, pastedContents, timestamp, project, sessionId}` (3,570 entries). `display` shows paste placeholders like `[Pasted text #1 +12 lines]`; the full text is in `pastedContents["1"].content` | No attachment files; flat global list; internal format; not queryable per-project |
| `~/.claude/projects/<slug>/<session>.jsonl` | Full transcripts. **Pasted images** live here as base64 blocks; **large pasted text** is inlined into the user message (no placeholder) | Huge, noisy, per-session; not a prompt index |

The raw data mostly exists but there is no clean, per-project, attachment-aware, **queryable + browsable + editable** layer. That is what this tool builds. We also **seed** from `history.jsonl` so all existing prompts are immediately searchable.

## 3. Scope (v1)

- Capture every prompt (typed text, including slash commands — **not** filtered out).
- Capture attached **files** referenced via `@path` mentions (snapshot as-sent).
- Capture pasted **images** (extracted from the transcript).
- Capture **large pasted text** (the transcript inlines it; captured as canonical prompt text, and stored as a text blob when very large).
- **Export** a selected set of prompts to a shareable file — **Markdown** (default,
  round-trippable) or **JSON** — reusing the CLI's scope/filters (`surfer export`).
- **Replay** an exported file into a fresh Claude Code session, playing prompts
  one at a time via the headless `claude` CLI, with flexible selection
  (`surfer replay`).
- Per-project organization; local-only data.
- **Recall + browse + curate:** `surfer` CLI, a **curses TUI browser**, a Claude skill, and a `/history` slash command.
- **Curation:** tag prompts, mark favorites, edit prompt text, and prune (delete) prompts — via a non-destructive overlay.
- **One-line install** (no manual clone required).
- One-time import of existing `history.jsonl`.
- **Comprehensive README**, written *after* the package is built and **verified for accuracy** (every documented command actually run).

**Out of scope (v1):** a web/GUI viewer; cross-machine sync; automatic retention/pruning policies.

## 4. Key architectural decision: hybrid capture

Neither data source is sufficient alone:

- The `UserPromptSubmit` hook's **stdin** (`{session_id, transcript_path, cwd, prompt, ...}`) is the **only** guaranteed record of *every* prompt (including client-side slash commands), but `prompt` is text-only (no images) and may carry paste *placeholders* rather than full text.
- The **transcript** is the **only** place pasted **images** exist (`{"type":"image","source":{"type":"base64",...}}`) and the only place large pasted **text** is inlined in full.

So the hook does both, and a `Stop` (end-of-turn) hook guarantees the final turn is reconciled after the transcript is fully flushed:

```
User submits prompt
      │
      ▼
UserPromptSubmit hook ── stdin: prompt text, cwd, session_id, transcript_path
      │  ├─ append prompt record (guarantees capture)           → prompts.jsonl
      │  ├─ snapshot @file refs (on disk now)                    → attachments/  + attachments.jsonl
      │  └─ best-effort transcript enrich (images, full text)
      ▼
Stop hook (turn complete, transcript flushed)
         └─ transcript enrich: finalize full text, pasted images → attachments.jsonl (+ attachments/)
```

**Capture / curation split (important):**
- **Capture layer is append-only and immutable** (`prompts.jsonl`, `attachments.jsonl`, `attachments/`). It always preserves what was actually sent.
- **Curation layer is a separate append-only overlay** (`overlay.jsonl`) holding tag/favorite/edit/delete *events*. Reads merge capture + overlay (latest event per prompt wins). Editing a prompt stores the new text in the overlay; the original is never lost. Pruning is a soft-delete flag by default (hard purge available explicitly).

**Hook invariants** (a logger must never break a session):
- Always exits `0`; never writes to **stdout** (UserPromptSubmit stdout is injected into the model context).
- All work in try/except → errors go to `meta/errors.log`, never surfaced.
- Standard-library only (no venv/pip) so it can't fail on a missing dependency.
- Bounded: reads only new transcript bytes (per-session offset); caps attachment size (configurable).

## 5. Storage layout (local-only, gitignored)

Data lives **outside** the code repo at `~/.claude/history-surfer/` (override via `CLAUDE_HISTORY_SURFER_DIR`).

```
~/.claude/history-surfer/
  projects/<project-slug>/            # slug mirrors Claude's own: "/" → "-"
    prompts.jsonl                     # append-only: prompt records, keyed (session_id, seq)
    attachments.jsonl                 # append-only: attachment records keyed to (session_id, seq)
    attachments/<sha256>.<ext>        # content-addressed, deduplicated (files, images, large-text blobs)
    overlay.jsonl                     # append-only curation events: tag/favorite/edit/delete
  state/<session_id>.json             # {"seq": N, "enrich_offset": bytes}
  meta/errors.log
```

**Prompt record** (`prompts.jsonl`):
```json
{"ts":"2026-06-30T21:00:00Z","session_id":"…","cwd":"/Users/jmanning/foo",
 "project_slug":"-Users-jmanning-foo","seq":42,"prompt":"full text…",
 "is_command":false,"text_final":true}
```
`text_final` flips to `true` once enrich confirms the canonical full text from the transcript; the reader prefers the latest record per `(session_id, seq)`.

**Attachment record** (`attachments.jsonl`), keyed to a prompt by `(session_id, seq)`:
```json
{"session_id":"…","seq":42,"kind":"image","media_type":"image/jpeg",
 "stored":"attachments/cd34….jpg","sha256":"cd34…","bytes":302432}
```
`kind` ∈ `file` | `image` | `text` (large paste blob).

**Overlay event** (`overlay.jsonl`), keyed to a prompt by `(session_id, seq)`:
```json
{"ts":"…","session_id":"…","seq":42,"op":"tag","value":"vector-field"}
{"ts":"…","session_id":"…","seq":42,"op":"favorite","value":true}
{"ts":"…","session_id":"…","seq":42,"op":"edit","value":"corrected text…"}
{"ts":"…","session_id":"…","seq":42,"op":"delete","value":true}
```

## 6. Access surfaces

All surfaces share one codebase. The store is the single source of truth.

**CLI `surfer`** (stdlib-only Python; symlinked to `~/.local/bin/surfer`):
- `surfer search <query> [--all] [--project PATH] [--regex] [--favorites] [--tag T] [--since DATE] [--limit N] [--json]` — defaults to the current project.
- `surfer list [--all] [--limit N]`
- `surfer show <id>` — full prompt + attachment paths (`id` = `session:seq` or a short prefix).
- `surfer stats`
- `surfer import-history` — one-time, idempotent seed from `~/.claude/history.jsonl` (including `pastedContents`).
- `surfer tag|untag|favorite|unfavorite|edit|delete|restore <id> …` — scriptable curation (the TUI wraps these).
- `surfer open <id|sha>` — reveal a stored attachment.
- `surfer tui` — launch the browser.

**TUI browser (`surfer tui`)** — curses (stdlib):
- List pane (current project or `--all`), incremental search/filter, favorites/tag filters.
- Detail pane: full prompt text, metadata, attachment list (open with a keypress).
- Actions: **tag** (`t`), **favorite** (`f`), **edit** (`e`, opens `$EDITOR`), **prune/delete** (`d`, soft by default), **restore** (`u`). All go through the overlay.

**Claude skill `history-surfer`** — installed to `~/.claude/skills/history-surfer/`. When the user asks to recall past prompts, Claude runs `surfer search … --json` and summarizes. Primary in-session recall path.

**Slash command `/history`** — `~/.claude/commands/history.md`, a thin user-facing entry to search.

## 7. Installation — one line, no manual clone

```
curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash
```

`install.sh` is a self-bootstrapping script:
1. If run **inside a clone** (package files present next to it) → use that directory as `APP_HOME`.
2. If run **standalone** (piped from curl) → `git clone` (or download tarball) to `APP_HOME` (default `~/.claude/history-surfer-app`), then continue.
3. Run `python3 $APP_HOME/scripts/setup.py`, which:
   - Symlinks `bin/surfer` → `~/.local/bin/surfer`.
   - **Merges** the `UserPromptSubmit` + `Stop` hooks into `~/.claude/settings.json` (backs it up first; preserves every existing key — settings.json is 31 KB of real config).
   - Symlinks skill → `~/.claude/skills/history-surfer`, command → `~/.claude/commands/history.md`.
   - Creates `~/.claude/history-surfer/`.
   - Offers to run `surfer import-history`.

`curl -fsSL …/main/uninstall.sh | bash` (and `scripts/setup.py --uninstall`) reverses everything and restores the settings.json backup.

## 8. Privacy

Prompt **data** is local-only and never pushed (gitignored; the real store lives under `~/.claude/`). It can contain secrets the user pasted; the README documents this and how to purge (`surfer delete --purge`, or remove the store). Only **code** is committed.

## 9. Testing (real, no mocks — per project convention)

- **Hook stdin probe (first build step):** install a throwaway hook that dumps real stdin, submit a real prompt (with a paste + `@file` + image), and record the exact schema — resolves whether `prompt` carries full text or placeholders. Design confirmed against reality before finalizing capture.
- **Hook:** real sample stdin → real record in a real temp store; `@file` snapshot created/hashed/deduped.
- **Images / large text:** real transcript `.jsonl` with a real base64 image block and a large inlined text block → enrich → assert files decoded to disk (correct ext + sha256), attached to the right `(session,seq)`; offset tracking skips already-read bytes.
- **End-to-end:** actually install, paste an image + large text in a live session, confirm capture (immediate or via `Stop` flush).
- **Overlay/curation:** tag/favorite/edit/delete via CLI → assert merged reads reflect them and capture files are untouched; restore works.
- **Settings merge:** real temp `settings.json` with existing keys → hooks added, nothing else changed, backup created.
- **CLI + TUI:** real store → `search/list/show/stats`; TUI actions drive the same overlay (tested via the underlying functions).
- **import-history:** real temp copy of `history.jsonl` (with `pastedContents`) → idempotent seeding.
- **Robustness:** empty prompt, non-UTF8, missing `@file`, oversized attachment (skipped w/ note), malformed transcript line.

## 10. Future (v2)

Web/GUI browser; cross-machine sync; automatic retention/pruning policy; full-text index for very large stores.
