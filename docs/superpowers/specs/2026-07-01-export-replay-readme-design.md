# Export, Replay & README overhaul — Design

_Date: 2026-07-01_

## 1. Goal

Extend `claude-history-surfer` with two user-facing features and a substantially
improved README:

1. **Export** a project's prompt history to a shareable file — **Markdown** or
   **JSON**.
2. **Replay** an exported file into a fresh Claude Code session, "playing" the
   prompts one-by-one to the model and waiting for each response, with flexible
   selection of which prompts to play.

Plus a friendlier, fuller README (motivation, visuals, docs for the new
features) and a new `dev/` folder documenting development + how the visual
assets are generated.

Hard constraints (unchanged from the project):
- **Python standard library only** — no pip packages. (This is why PDF/DOCX
  export was dropped: only Markdown and JSON, both plain text.)
- Capture layer stays append-only and immutable; these features are **read-only**
  over the store (export) or drive an external CLI (replay). Neither mutates
  captured data.

## 2. Feature 1 — `surfer export`

Serialize a selected set of prompts to Markdown or JSON. Reuses the existing
selection/filter machinery (`cli._rows_for` + `cli._filter`), so any subset you
can `search`/`list` you can also export.

```bash
surfer export                                 # current project → Markdown to stdout
surfer export --format json -o prompts.json   # JSON to a file
surfer export --all --favorites -o faves.md   # all projects, favorites only
surfer export "vector" --tag graphics --since 2026-01-01 -o graphics.md
```

**Flags**
- `--format {md,json}` — default `md`.
- `-o, --output FILE` — default: stdout.
- Optional positional `query` (same as `search`).
- Scope/filters shared with the rest of the CLI: `--all`, `--project`,
  `--favorites`, `--tag`, `--since`, `--limit`, `--regex`.

**Ordering / indices.** Export order is the store's canonical order
(`ts`, then `seq`). Each exported prompt gets a 0-based `index` in that order.
Replay selection (§4) is defined over these indices.

### 2.1 JSON format (canonical, lossless)

```json
{
  "surfer_export": {
    "version": 1,
    "exported_at": "2026-07-01T12:00:00Z",
    "scope": "project",
    "filters": {"query": null, "tag": "graphics", "since": "2026-01-01",
                "favorites": false, "all": false},
    "count": 3
  },
  "prompts": [
    {
      "index": 0,
      "id": "3f7b0a97:42",
      "ts": "2026-06-30T21:00:00Z",
      "project": "/Users/jmanning/foo",
      "prompt": "full prompt text…",
      "tags": ["graphics"],
      "favorite": true,
      "is_command": false,
      "attachments": [
        {"kind": "image", "name": null, "sha256": "cd34…", "bytes": 302432}
      ]
    }
  ]
}
```

Attachment **metadata only** in v1 (kind/name/sha256/bytes) — not raw bytes.

### 2.2 Markdown format (human-readable **and** round-trippable)

Each prompt is wrapped in HTML-comment markers so it re-imports losslessly. The
comments are invisible when rendered (e.g. on GitHub); the decorative heading is
*outside* the markers and is ignored on import.

````markdown
# 🏄 Prompt history — foo
<!-- surfer-export version=1 exported=2026-07-01T12:00:00Z scope=project count=3 -->

### Prompt 0 · 2026-06-30 21:00 · ★ · #graphics
<!-- surfer:prompt index=0 id=3f7b0a97:42 ts=2026-06-30T21:00:00Z favorite=true tags=graphics -->
Add a vector field overlay to the plot and animate it over time.
<!-- /surfer:prompt -->

### Prompt 1 · 2026-06-30 21:05
<!-- surfer:prompt index=1 id=3f7b0a97:43 ts=2026-06-30T21:05:00Z favorite=false -->
Now write a test that renders the animation to a PNG and checks the frame count.
<!-- /surfer:prompt -->
````

**Exact serialization (defines the round-trip):** for each prompt the exporter
writes the opening marker line, then `\n`, then the verbatim prompt text, then
`\n`, then the closing marker line. The parser takes the bytes strictly between
the opening marker's trailing newline and the newline preceding the closing
marker — removing exactly the one boundary newline inserted on each side, so a
prompt that itself begins/ends with newlines survives intact.

**Attribute encoding.** Space-separated `key=value` in the opening comment.
Values contain no spaces; `tags` is comma-joined (`tags=a,b,c`); empty tag list
omits the `tags` key. Booleans are `true`/`false`.

## 3. Round-trip parser (Markdown import)

`exporter.parse_export(text_or_path)` returns the same normalized list of prompt
dicts that the JSON `prompts` array holds, for **either** format (dispatch by
detecting a leading `{` / `.json` extension vs. Markdown markers).

Markdown parsing algorithm:
1. Scan for `<!-- surfer:prompt … -->` … `<!-- /surfer:prompt -->` blocks with a
   non-greedy regex over the whole document.
2. For each block: parse the opening comment's `key=value` attributes; extract
   verbatim text per the boundary-newline rule above.
3. Coerce attributes: `index`→int, `favorite`→bool, `tags`→list (split on `,`),
   others→str. Missing keys default sensibly (`tags=[]`, `favorite=false`).
4. Return blocks in document order, each `{index, id, ts, prompt, tags,
   favorite, …}`.

Robust to arbitrary prompt content, including prompts that contain their own
```` ``` ```` fences or `<!-- -->` comments that are **not** our markers (only
`surfer:prompt` / `/surfer:prompt` markers are recognized).

## 4. Feature 2 — `surfer replay`

Play prompts from an exported file into a fresh Claude Code session, one at a
time, waiting for each response before sending the next.

```bash
surfer replay prompts.json                     # replay all, in export order
surfer replay prompts.md --select "0,3-7,10-"  # subset (brackets/spaces optional)
surfer replay prompts.json --first 5           # first 5
surfer replay prompts.json --last 3            # last 3
surfer replay prompts.json --dry-run           # print what WOULD be sent (no tokens)
```

**Flags**
- positional `file` — a surfer-produced `.json` or `.md`.
- `--select SPEC` — selection spec (§4.1). Mutually exclusive with `--first/--last`.
- `--first N` / `--last N` — shortcuts.
- `--dry-run` — parse + select + print the plan and each prompt; do **not** invoke `claude`.
- `--model MODEL` — passthrough to `claude`.
- `-o, --output FILE` — also write the replayed prompt/response exchange to Markdown.
- `--session-id UUID` — use/resume a specific session (default: a fresh uuid4).

### 4.1 Selection spec (`parse_selection`)

Grammar (brackets and internal whitespace optional): comma-separated tokens,
each one of:
- `N` — a single 0-based index.
- `A-B` — inclusive range `A..B`.
- `A-` — open end: `A..last`.
- `-B` — open start: `0..B`.

Semantics (**as chosen**):
- **Order matters:** tokens are expanded left-to-right and concatenated; the
  resulting list *is* the execution order. `"10-,0,3-5"` runs 10…end, then 0,
  then 3,4,5.
- **Duplicates are kept:** a repeated index re-runs that prompt again.
- **Out-of-range indices warn and are skipped:** print a warning to **stderr**
  and drop them; never abort. If the selection ends up **empty** (every index
  out of range), print the warnings and submit **nothing** to `claude` — a clean
  no-op replay, *not* an error (same behavior as when only some indices are out
  of range).
- `--first N` ≡ `0-(N-1)`; `--last N` ≡ `(count-N)-(count-1)` (clamped at 0).

Signature: `parse_selection(spec: str, count: int) -> tuple[list[int], list[str]]`
returning `(indices_in_execution_order, warnings)`.

### 4.2 Replay engine (drives the `claude` CLI)

Verified available: `claude -p/--print`, `--session-id <uuid>`, `-r/--resume
<uuid>`, `--output-format`.

- Generate a `uuid4` session id (unless `--session-id`).
- **First** selected prompt: `claude -p <text> --session-id <uuid> [--model M]`.
- **Each subsequent** prompt: `claude -p <text> --resume <uuid> [--model M]`.
- Run synchronously (`subprocess.run`), capture stdout, echo a header
  (`▶ Prompt k/N …`) + the model's response, then proceed. This yields the
  "wait for each response, then send the next" behavior and accumulates context
  like a real conversation.
- The exact first-call/continue handshake is confirmed by a **real** end-to-end
  test (one cheap `claude -p` call); `--dry-run` covers argv/order without cost.

**Attachments (v1 limitation, documented).** Replay sends prompt **text
as-sent**. `@file` references are replayed literally and re-resolve live if the
files still exist. Pasted images / large-text blobs are **not** re-attached.

## 5. Module layout

- `history_surfer/exporter.py` — `build_export_records(rows) -> list[dict]`,
  `to_json(records, meta) -> str`, `to_markdown(records, meta) -> str`,
  `parse_export(text_or_path) -> list[dict]` (md + json). Export serialization
  and import parsing live together so the round-trip can't drift.
- `history_surfer/replay.py` — `parse_selection(spec, count)`, `select(records,
  args)`, `run_replay(records, indices, opts)` (drives `claude`), Markdown
  transcript writer.
- `history_surfer/cli.py` — new `cmd_export`, `cmd_replay`, argparse wiring;
  reuses `_rows_for`/`_filter` for export scope.

## 6. README overhaul

- 🏄 header + one-line tagline.
- **Why** expanded: an intuitive, *searchable interface to your own past
  prompts* — for **reusing** wording/sequences that worked and **referencing**
  what you asked before. Concrete scenarios (re-run a project's setup prompt
  sequence elsewhere; recover the exact phrasing that produced a good result;
  audit what you've asked about a topic).
- **Install defaults to the import-history one-liner**; the plain install and the
  clone install are shown as alternatives.
- Embedded **GIF** + still **screenshots** (from a synthetic store, §7).
- New **Export** and **Replay** sections mirroring §2 and §4.
- **Development** section points to `dev/`.
- Friendlier, less clipped prose throughout.
- Every command is actually run and every link resolved before commit.
- Tables keep the minimal `|-|-|` separator style already in use.

## 7. Visual assets + `dev/` folder

- New `dev/README.md`: running tests, generating media (install `vhs`, the
  `.tape` scripts, `generate_media.sh`), dev-only dependencies, an architecture
  deep-dive (summarizing/referencing `docs/design.md`), and design notes for the
  new features (this file).
- `dev/*.tape` + `dev/generate_media.sh` record the CLI + TUI + export/replay
  demos with **`vhs`** into `docs/media/*.gif` (+ still frames).
- Media is recorded against a **throwaway synthetic store**
  (`CLAUDE_HISTORY_SURFER_DIR=$(mktemp -d)` seeded with fabricated example
  prompts), so no real prompts, paths, or secrets enter the repo.
- The **user `install.sh` is untouched** — `vhs` is a developer-only dependency.

## 8. Testing (real, no mocks — repo convention)

- **Export round-trip:** export a real temp store to md and to json →
  `parse_export` → assert recovered prompt text/metadata equals the source, for
  content including code fences, unicode, leading/trailing newlines, and
  slash-command prompts.
- **Selection spec:** table of `(spec, count) → (indices, warnings)` covering
  single/range/open-start/open-end, order preservation, duplicates, out-of-range
  warnings, `--first/--last`, empty/garbage tokens.
- **Replay dry-run:** assert the exact `claude` argv sequence and prompt order
  for a selection, with no process spawned.
- **Empty selection:** a selection where every index is out of range prints
  warnings, spawns no process, and exits cleanly (no error).
- **Replay live (one call):** a single real `claude -p` round-trip to confirm the
  `--session-id` → `--resume` handshake actually continues a session.
- **CLI wiring:** `surfer export`/`surfer replay --dry-run` end-to-end against a
  temp store.
- **README accuracy:** run each documented command; validate each link.

## 9. Out of scope (v1)

Re-attaching images/blobs on replay; exporting attachment bytes; PDF/DOCX;
parallel/async replay; replay into non-Claude-Code backends.
