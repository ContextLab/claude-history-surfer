# claude-history-surfer — Design

_Last updated: 2026-06-30_

## 1. Goal

Maintain a durable, searchable log of **every prompt** sent to Claude Code, across **all projects**, including **files and images the user attaches** to the conversation — and make past prompts **easy to recall from inside any Claude Code session**.

## 2. What Claude Code already provides (and why it isn't enough)

Research into the local `~/.claude/` install found two existing stores:

| Store | Contents | Gap |
|-|-|-|
| `~/.claude/history.jsonl` | One line per submitted prompt, all projects: `{display, pastedContents, timestamp, project, sessionId}` (3,570 entries currently) | No attachment files; flat global list; internal format; not organized per-project or searchable ergonomically |
| `~/.claude/projects/<slug>/<session>.jsonl` | Full session transcripts: every message + tool call. Pasted **images** live here as base64 content blocks | Huge, noisy, per-session; not a prompt index; format is internal |

So the raw data mostly exists, but there is no clean, per-project, attachment-aware, **queryable** layer. That layer is what this tool builds. We also **seed** from `history.jsonl` so all 3,570 historical prompts are immediately searchable.

## 3. Scope

**In scope (v1):**
- Capture every prompt (typed text, including slash commands — **not** filtered out).
- Capture attached **files** referenced via `@path` mentions (snapshot as-sent).
- Capture pasted **images** (extracted from the transcript).
- Per-project organization; local-only data.
- CLI + Claude skill + `/history` slash command for recall.
- One-time import of existing `history.jsonl`.

**Out of scope (v1):** capturing large pasted *text* blobs beyond what appears inline in the prompt; a GUI/web viewer; cross-machine sync; editing/redacting stored prompts. (Noted as possible future work.)

## 4. Key architectural decision: hybrid capture

Neither available data source is sufficient alone:

- The `UserPromptSubmit` hook receives on **stdin**: `{session_id, transcript_path, cwd, prompt, hook_event_name, ...}`. `prompt` is **text only** — no images. But it is the **only** guaranteed record of *every* prompt (including client-side slash commands that may never enter the transcript).
- The **transcript** (`transcript_path`) is the **only** place pasted images exist, as user-message content blocks:
  `{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"<base64>"}}`.

Therefore the hook does **both** on each fire:

1. **Record from stdin** — append a prompt record immediately (guarantees capture of every prompt).
2. **Sync from transcript tail** — read only the *new* bytes since the last sync (tracked by a per-session byte offset), extract any user-message image blocks + `@`-file references, snapshot them, and attach to the matching record (matched by `session_id` + prompt text).

A `Stop` (session-end) hook runs a final transcript sync so the **last** turn's images are never missed (they may not be flushed to the transcript at `UserPromptSubmit` time).

```
User submits prompt
      │
      ▼
UserPromptSubmit hook (log_prompt.py)   ── stdin: prompt text, cwd, session_id, transcript_path
      │
      ├─ append record  ──────────────►  projects/<slug>/prompts.jsonl
      ├─ snapshot @file refs ─────────►  projects/<slug>/attachments/<sha256>.<ext>
      └─ sync transcript tail (images) ►  projects/<slug>/attachments/<sha256>.<ext>
                                          state/<session_id>.json  (byte offset)
Stop hook ── final transcript sync (flush last turn's images)
```

**Design invariants for the hook** (non-negotiable — a logger must never break the user's session):
- Always exits `0`. Never writes to **stdout** (stdout from a `UserPromptSubmit` hook is injected into the model's context).
- All work wrapped in try/except; internal errors go to `~/.claude/history-surfer/meta/errors.log`, never surfaced.
- Standard-library only (no venv, no pip) so it can't fail on a missing dependency.
- Bounded work: reads only new transcript bytes; caps attachment size (configurable).

## 5. Storage layout (local-only, gitignored)

Data lives **outside** the code repo at `~/.claude/history-surfer/` so re-cloning/moving the code never risks the data. Location overridable via `CLAUDE_HISTORY_SURFER_DIR`.

```
~/.claude/history-surfer/
  projects/
    <project-slug>/                 # slug mirrors Claude's own: "/" → "-"
      prompts.jsonl                 # append-only, one record per prompt
      attachments/<sha256>.<ext>    # content-addressed, deduplicated
  state/<session_id>.json           # {"offset": <bytes>, "last_uuid": "..."}
  meta/errors.log
```

**Prompt record:**
```json
{
  "ts": "2026-06-30T21:00:00Z",
  "session_id": "4eebc3c2-…",
  "cwd": "/Users/jmanning/foo",
  "project_slug": "-Users-jmanning-foo",
  "seq": 42,
  "prompt": "full prompt text …",
  "is_command": false,
  "source": "hook",
  "attachments": [
    {"kind": "file",  "ref": "@src/x.py", "stored": "attachments/ab12….py", "sha256": "ab12…", "bytes": 1234},
    {"kind": "image", "media_type": "image/jpeg", "stored": "attachments/cd34….jpg", "sha256": "cd34…", "bytes": 302432}
  ]
}
```
- **Content-addressed attachments**: identical file/image stored once; snapshot is immutable, so a prompt always shows the file *as it was when sent*.
- `is_command`: `true` for `/`-prefixed prompts — **tagged but included by default** (per user: don't filter commands out).

## 6. Access surfaces

One CLI, wrapped by a skill and a slash command (all share the same code).

**CLI `surfer`** (stdlib-only Python; symlinked to `~/.local/bin/surfer`):
- `surfer search <query> [--all] [--project PATH] [--regex] [--since DATE] [--limit N] [--json]` — defaults to the **current project**; `--all` searches everywhere.
- `surfer list [--all] [--limit N]` — most recent prompts.
- `surfer show <session_id:seq | sha-prefix>` — full prompt + attachment paths.
- `surfer stats` — counts per project / totals.
- `surfer import-history` — one-time, idempotent seed from `~/.claude/history.jsonl`.
- `surfer open <attachment-sha>` — reveal/open a stored attachment.

**Claude skill `history-surfer`** — installed to `~/.claude/skills/history-surfer/`. Tells Claude that when the user asks to recall past prompts ("what did I ask about X earlier?", "find my previous prompt about the vector field") it should run `surfer search …` and summarize. This is the primary in-session recall path.

**Slash command `/history`** — installed to `~/.claude/commands/history.md`, a thin user-facing entry to the same search.

## 7. Installation

`install.sh` (idempotent):
1. Symlink `bin/surfer` → `~/.local/bin/surfer`.
2. **Merge** the `UserPromptSubmit` + `Stop` hooks into `~/.claude/settings.json` using a Python JSON merge that **backs up first** and **preserves all existing keys** (settings.json is 31 KB of real config — must not be clobbered).
3. Symlink skill → `~/.claude/skills/history-surfer`, command → `~/.claude/commands/history.md`.
4. Create `~/.claude/history-surfer/`.
5. Offer to run `surfer import-history`.

`uninstall.sh` reverses all of the above (restoring the settings.json backup).

## 8. Privacy

- Prompt **data** is local-only and **gitignored** (`data/`, and the real store lives under `~/.claude/history-surfer/` anyway). Only **code** is committed.
- The store can contain secrets the user pasted; it is never pushed. README documents this and how to purge (`surfer` delete or removing the store).

## 9. Testing (real, no mocks — per user convention)

- **Hook**: feed real sample stdin JSON → assert a real record lands in a real temp store; assert `@file` snapshot created, hashed, deduped.
- **Images**: build a real transcript `.jsonl` with a real base64 image block → run sync → assert the image file is decoded to disk with correct extension + sha256, and attached to the right record. Verify offset tracking skips already-read bytes.
- **Timing**: real end-to-end — actually paste an image in a live session and confirm capture (immediate or via the `Stop` flush).
- **Settings merge**: run against a real temp `settings.json` containing existing keys → assert hooks added and nothing else changed; assert backup created.
- **CLI**: real store → assert `search`/`list`/`show`/`stats` outputs.
- **import-history**: real (temp copy of) `history.jsonl` → assert idempotent seeding.
- **Robustness**: empty prompt, non-UTF8, missing `@file`, oversized attachment (skipped with note), malformed transcript line.

## 10. Future (v2, not built now)

Large pasted-text capture; a web/TUI browser; tagging/favorites; cross-machine sync of the store; retention/pruning policy.
