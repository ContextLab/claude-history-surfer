# Export, Replay & README Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `surfer export` (Markdown/JSON) and `surfer replay` (play exported prompts into a Claude Code session), and overhaul the README with motivation, visuals, and docs for the new features.

**Architecture:** Two new pure-stdlib modules — `exporter.py` (serialize + round-trip parse) and `replay.py` (selection spec + drive the `claude` CLI) — wired into `cli.py` as `export`/`replay` subcommands, reusing the existing scope/filter helpers. Export and import share one normalized record shape so the round-trip can't drift. Developer-only media tooling (vhs) lives in a new `dev/` folder, excluded from the user installer.

**Tech Stack:** Python 3 standard library only (`argparse`, `json`, `re`, `subprocess`, `uuid`, `pathlib`); `unittest` for tests; the installed `claude` CLI for replay; `vhs` (dev-only) for media.

## Global Constraints

- **Python standard library only** — no pip packages, anywhere in `history_surfer/`.
- **Never mutate captured data** — export is read-only; replay drives an external CLI. No writes to `prompts.jsonl`/`attachments.jsonl`/`overlay.jsonl`.
- **Tests are real, no mocks** — real temp stores via `CLAUDE_HISTORY_SURFER_DIR`; the one live replay test calls the real `claude` CLI (guarded by `CLAUDE_HISTORY_SURFER_LIVE=1`).
- **Test style:** stdlib `unittest`; each `tests/test_*.py` ends with `unittest.main()`; run with `python3 tests/test_x.py -v` (or `./run_tests.sh`).
- **Export formats:** `md` (default) and `json` only. No PDF/DOCX.
- **Selection semantics:** argument order = execution order; duplicates re-run; out-of-range indices warn on stderr and are skipped; a fully-empty selection is a clean no-op (no error, nothing sent to `claude`).
- **Tables in docs:** minimal `|-|-|` separators.
- **Installer untouched:** `install.sh`/`installer.py` must not reference `vhs` or `dev/`.

## File Structure

- Create `history_surfer/exporter.py` — record building, JSON + Markdown serialization, round-trip parsing.
- Create `history_surfer/replay.py` — selection spec, index selection, `claude` argv building, replay runner, transcript writer.
- Modify `history_surfer/cli.py` — add `cmd_export`, `cmd_replay`, argparse wiring.
- Create `tests/test_exporter.py`, `tests/test_replay.py`; add replay/export CLI cases to `tests/test_cli.py`.
- Create `dev/README.md`, `dev/seed_demo_store.py`, `dev/cli.tape`, `dev/tui.tape`, `dev/export_replay.tape`, `dev/generate_media.sh`.
- Create `docs/media/` (generated GIF + stills).
- Modify `README.md`, `docs/design.md`, `.gitignore` (allow `docs/media/`, ignore dev scratch).

---

## Task 1: Export record builder

**Files:**
- Create: `history_surfer/exporter.py`
- Test: `tests/test_exporter.py`

**Interfaces:**
- Consumes: merged prompt dicts from `store.load_project`/`store.load_all` (keys: `id`, `session_id`, `seq`, `ts`, `cwd`, `prompt`, `tags`, `favorite`, `is_command`, `attachments`).
- Produces: `build_export_records(rows) -> list[dict]`; each record `{index:int, id:str, ts:str, project:str, prompt:str, tags:list[str], favorite:bool, is_command:bool, attachments:list[dict]}` where each attachment is `{kind, name, sha256, bytes}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exporter.py
"""Real tests for history_surfer.exporter (build/serialize/round-trip)."""
import json
import os
import tempfile
import unittest


class ExporterTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import exporter
        self.exporter = exporter

    def _rows(self):
        return [
            {"id": "sessA:1", "session_id": "sessA", "seq": 1,
             "ts": "2026-06-01T10:00:00Z", "cwd": "/proj/a",
             "prompt": "fix the vector field bug", "tags": ["graphics"],
             "favorite": True, "is_command": False,
             "attachments": [{"kind": "image", "name": None,
                              "sha256": "cd34", "bytes": 7, "stored": "attachments/cd34.png"}]},
            {"id": "sessA:2", "session_id": "sessA", "seq": 2,
             "ts": "2026-06-02T10:00:00Z", "cwd": "/proj/a",
             "prompt": "add tests for the parser", "tags": [],
             "favorite": False, "is_command": False, "attachments": []},
        ]

    def test_build_records_indexes_and_att_meta(self):
        recs = self.exporter.build_export_records(self._rows())
        self.assertEqual([r["index"] for r in recs], [0, 1])
        self.assertEqual(recs[0]["id"], "sessA:1")
        self.assertEqual(recs[0]["tags"], ["graphics"])
        self.assertTrue(recs[0]["favorite"])
        # attachment reduced to metadata only (no 'stored' path / raw bytes)
        att = recs[0]["attachments"][0]
        self.assertEqual(set(att), {"kind", "name", "sha256", "bytes"})
        self.assertEqual(att["sha256"], "cd34")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'history_surfer.exporter'`.

- [ ] **Step 3: Write minimal implementation**

```python
# history_surfer/exporter.py
"""Export prompts to Markdown/JSON and parse them back (the round-trip pair).

Export is read-only over the store. The Markdown format wraps each prompt's
verbatim text in HTML-comment markers so it re-imports losslessly.
"""

import json
import re
from pathlib import Path


def _att_meta(a):
    return {"kind": a.get("kind"), "name": a.get("name"),
            "sha256": a.get("sha256"), "bytes": a.get("bytes")}


def build_export_records(rows):
    """Normalize merged store rows into ordered, index-stamped export records."""
    records = []
    for i, r in enumerate(rows):
        rid = r.get("id") or ("%s:%s" % (r.get("session_id"), r.get("seq")))
        records.append({
            "index": i,
            "id": rid,
            "ts": r.get("ts"),
            "project": r.get("cwd"),
            "prompt": r.get("prompt") or "",
            "tags": list(r.get("tags") or []),
            "favorite": bool(r.get("favorite")),
            "is_command": bool(r.get("is_command")),
            "attachments": [_att_meta(a) for a in (r.get("attachments") or [])],
        })
    return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_surfer/exporter.py tests/test_exporter.py
git commit -m "feat(export): normalized export record builder"
```

---

## Task 2: JSON serialization + export metadata

**Files:**
- Modify: `history_surfer/exporter.py`
- Test: `tests/test_exporter.py`

**Interfaces:**
- Produces: `to_json(records, meta) -> str` returning `json.dumps({"surfer_export": meta, "prompts": records}, ...)`; `meta` is `{version:int, exported_at:str, scope:str, filters:dict, count:int}`.

- [ ] **Step 1: Write the failing test** (append to `ExporterTest`)

```python
    def test_to_json_shape(self):
        recs = self.exporter.build_export_records(self._rows())
        meta = {"version": 1, "exported_at": "2026-07-01T12:00:00Z",
                "scope": "project", "filters": {"all": False}, "count": len(recs)}
        data = json.loads(self.exporter.to_json(recs, meta))
        self.assertEqual(data["surfer_export"]["version"], 1)
        self.assertEqual(data["surfer_export"]["count"], 2)
        self.assertEqual(len(data["prompts"]), 2)
        self.assertEqual(data["prompts"][0]["prompt"], "fix the vector field bug")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: FAIL — `AttributeError: module 'history_surfer.exporter' has no attribute 'to_json'`.

- [ ] **Step 3: Write minimal implementation** (append to `exporter.py`)

```python
def to_json(records, meta):
    return json.dumps({"surfer_export": meta, "prompts": records},
                      ensure_ascii=False, indent=2, default=str)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_surfer/exporter.py tests/test_exporter.py
git commit -m "feat(export): JSON serialization"
```

---

## Task 3: Markdown serialization

**Files:**
- Modify: `history_surfer/exporter.py`
- Test: `tests/test_exporter.py`

**Interfaces:**
- Produces: `to_markdown(records, meta) -> str`. Each prompt is emitted as: a decorative `### Prompt N · …` heading, then `<!-- surfer:prompt index=N id=… ts=… favorite=true|false [tags=a,b] -->`, then the verbatim prompt on its own line(s), then `<!-- /surfer:prompt -->`. Blocks are joined by blank lines; the document ends with a trailing newline.

- [ ] **Step 1: Write the failing test** (append to `ExporterTest`)

```python
    def test_to_markdown_has_markers_and_text(self):
        recs = self.exporter.build_export_records(self._rows())
        meta = {"version": 1, "exported_at": "2026-07-01T12:00:00Z",
                "scope": "project", "filters": {}, "count": len(recs)}
        md = self.exporter.to_markdown(recs, meta)
        self.assertIn("# 🏄 Prompt history", md)
        self.assertIn("<!-- surfer-export version=1", md)
        self.assertIn("<!-- surfer:prompt index=0 id=sessA:1", md)
        self.assertIn("favorite=true tags=graphics -->", md)
        self.assertIn("fix the vector field bug", md)
        self.assertIn("<!-- /surfer:prompt -->", md)
        self.assertTrue(md.endswith("\n"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: FAIL — no attribute `to_markdown`.

- [ ] **Step 3: Write minimal implementation** (append to `exporter.py`)

```python
def _human_ts(ts):
    return (ts or "")[:16].replace("T", " ")


def to_markdown(records, meta):
    scope_label = "all projects" if meta.get("scope") == "all" else "current project"
    out = ["# 🏄 Prompt history — %s" % scope_label,
           "<!-- surfer-export version=%s exported=%s scope=%s count=%s -->"
           % (meta.get("version"), meta.get("exported_at"),
              meta.get("scope"), meta.get("count")),
           ""]
    for r in records:
        tags = r.get("tags") or []
        star = " · ★" if r.get("favorite") else ""
        tagline = (" · " + " ".join("#" + t for t in tags)) if tags else ""
        out.append("### Prompt %d · %s%s%s"
                   % (r["index"], _human_ts(r.get("ts")), star, tagline))
        attrs = "index=%d id=%s ts=%s favorite=%s" % (
            r["index"], r.get("id"), r.get("ts"),
            "true" if r.get("favorite") else "false")
        if tags:
            attrs += " tags=" + ",".join(tags)
        out.append("<!-- surfer:prompt %s -->" % attrs)
        out.append(r.get("prompt") or "")
        out.append("<!-- /surfer:prompt -->")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_surfer/exporter.py tests/test_exporter.py
git commit -m "feat(export): Markdown serialization with round-trip markers"
```

---

## Task 4: Round-trip parser (Markdown + JSON import)

**Files:**
- Modify: `history_surfer/exporter.py`
- Test: `tests/test_exporter.py`

**Interfaces:**
- Produces: `parse_export_text(text) -> list[dict]` and `parse_export_file(path) -> list[dict]`. JSON input (leading `{`) returns its `prompts` array; Markdown input returns one record per `surfer:prompt` block with `{index, id, ts, favorite, tags, prompt}`, `prompt` recovered **verbatim**.

- [ ] **Step 1: Write the failing test** (append to `ExporterTest`) — covers hard cases: code fences, unicode, leading/trailing newlines.

```python
    def _roundtrip_rows(self):
        return [
            {"id": "s:1", "session_id": "s", "seq": 1, "ts": "2026-06-01T10:00:00Z",
             "cwd": "/p", "prompt": "plain prompt", "tags": ["x"], "favorite": True,
             "is_command": False, "attachments": []},
            {"id": "s:2", "session_id": "s", "seq": 2, "ts": "2026-06-02T10:00:00Z",
             "cwd": "/p", "prompt": "with a fence:\n```python\nprint('hi')\n```\nend",
             "tags": [], "favorite": False, "is_command": False, "attachments": []},
            {"id": "s:3", "session_id": "s", "seq": 3, "ts": "2026-06-03T10:00:00Z",
             "cwd": "/p", "prompt": "\nleading and trailing newline\n",
             "tags": [], "favorite": False, "is_command": False, "attachments": []},
            {"id": "s:4", "session_id": "s", "seq": 4, "ts": "2026-06-04T10:00:00Z",
             "cwd": "/p", "prompt": "unicode: café ✅ 日本語", "tags": [], "favorite": False,
             "is_command": False, "attachments": []},
        ]

    def test_markdown_round_trip_is_lossless(self):
        recs = self.exporter.build_export_records(self._roundtrip_rows())
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        md = self.exporter.to_markdown(recs, meta)
        parsed = self.exporter.parse_export_text(md)
        self.assertEqual([p["prompt"] for p in parsed], [r["prompt"] for r in recs])
        self.assertEqual(parsed[0]["tags"], ["x"])
        self.assertTrue(parsed[0]["favorite"])
        self.assertFalse(parsed[1]["favorite"])
        self.assertEqual([p["index"] for p in parsed], [0, 1, 2, 3])

    def test_json_round_trip(self):
        recs = self.exporter.build_export_records(self._roundtrip_rows())
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        js = self.exporter.to_json(recs, meta)
        parsed = self.exporter.parse_export_text(js)
        self.assertEqual([p["prompt"] for p in parsed], [r["prompt"] for r in recs])

    def test_parse_export_file(self):
        recs = self.exporter.build_export_records(self._roundtrip_rows())
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as tf:
            tf.write(self.exporter.to_markdown(recs, meta))
            path = tf.name
        try:
            parsed = self.exporter.parse_export_file(path)
            self.assertEqual(len(parsed), 4)
        finally:
            os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: FAIL — no attribute `parse_export_text`.

- [ ] **Step 3: Write minimal implementation** (append to `exporter.py`)

```python
_BLOCK_RE = re.compile(
    r"<!-- surfer:prompt (?P<attrs>.*?) -->\n(?P<text>.*?)\n<!-- /surfer:prompt -->",
    re.DOTALL)


def _coerce_attrs(attrs):
    d = {}
    for tok in attrs.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    idx = d.get("index", "")
    return {
        "index": int(idx) if idx.lstrip("-").isdigit() else None,
        "id": d.get("id"),
        "ts": d.get("ts"),
        "favorite": d.get("favorite") == "true",
        "tags": d["tags"].split(",") if d.get("tags") else [],
    }


def parse_export_text(text):
    """Parse a surfer-produced export (JSON or Markdown) into prompt records."""
    if text.lstrip().startswith("{"):
        return json.loads(text).get("prompts", [])
    records = []
    for m in _BLOCK_RE.finditer(text):
        rec = _coerce_attrs(m.group("attrs"))
        rec["prompt"] = m.group("text")
        records.append(rec)
    for i, rec in enumerate(records):
        if rec.get("index") is None:
            rec["index"] = i
    return records


def parse_export_file(path):
    return parse_export_text(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_exporter.py -v`
Expected: PASS (all exporter tests).

- [ ] **Step 5: Commit**

```bash
git add history_surfer/exporter.py tests/test_exporter.py
git commit -m "feat(export): lossless Markdown/JSON round-trip parser"
```

---

## Task 5: CLI `export` command

**Files:**
- Modify: `history_surfer/cli.py` (add `cmd_export`, `_export_meta`, argparse parser)
- Test: `tests/test_cli.py` (add cases to `CliTest`)

**Interfaces:**
- Consumes: `exporter.build_export_records`, `exporter.to_json`, `exporter.to_markdown`; existing `cli._rows_for`, `cli._filter`.
- Produces: `surfer export [query] [--all|--project P] [--regex] [--favorites] [--tag T] [--since D] [--limit N] [--format md|json] [-o FILE]`.

- [ ] **Step 1: Write the failing test** (append to `CliTest` in `tests/test_cli.py`)

```python
    def test_export_markdown_stdout(self):
        rc, out = self.run_cli(["export", "--project", "/proj/a"])
        self.assertEqual(rc, 0)
        self.assertIn("<!-- surfer:prompt", out)
        self.assertIn("fix the vector field bug", out)

    def test_export_json_to_file(self):
        path = os.path.join(self.tmp, "out.json")
        rc, _ = self.run_cli(["export", "--project", "/proj/a",
                              "--format", "json", "-o", path])
        self.assertEqual(rc, 0)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["surfer_export"]["scope"], "project")
        self.assertGreaterEqual(data["surfer_export"]["count"], 3)

    def test_export_respects_filters(self):
        self.run_cli(["favorite", "sessA:1"])
        rc, out = self.run_cli(["export", "--project", "/proj/a", "--favorites"])
        self.assertEqual(rc, 0)
        self.assertIn("fix the vector field bug", out)
        self.assertNotIn("add tests for the parser", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_cli.py -v`
Expected: FAIL — `export` is not a recognized command (argparse error / nonzero rc).

- [ ] **Step 3: Write minimal implementation**

In `history_surfer/cli.py`, add the command function (near the other `cmd_*`):

```python
def _export_meta(args, count):
    return {
        "version": 1,
        "exported_at": store.now_iso(),
        "scope": "all" if getattr(args, "all", False) else "project",
        "filters": {"query": args.query, "tag": args.tag, "since": args.since,
                    "favorites": bool(args.favorites),
                    "all": bool(getattr(args, "all", False))},
        "count": count,
    }


def cmd_export(args):
    from . import exporter
    rows = _filter(_rows_for(args), query=args.query, regex=args.regex,
                   favorites=args.favorites, tag=args.tag, since=args.since)
    if args.limit:
        rows = rows[-args.limit:]
    records = exporter.build_export_records(rows)
    meta = _export_meta(args, len(records))
    text = (exporter.to_json(records, meta) if args.format == "json"
            else exporter.to_markdown(records, meta))
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(text, encoding="utf-8")
        print("Exported %d prompt(s) to %s" % (len(records), args.output),
              file=sys.stderr)
    else:
        print(text)
    return 0
```

In `build_parser`, after the `search` parser block, add:

```python
    sp = sub.add_parser("export", help="export prompts to Markdown or JSON")
    sp.add_argument("query", nargs="?")
    add_scope(sp)
    sp.add_argument("--regex", action="store_true")
    sp.add_argument("--favorites", action="store_true")
    sp.add_argument("--tag")
    sp.add_argument("--since", help="ISO date, e.g. 2026-06-01")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--format", choices=["md", "json"], default="md")
    sp.add_argument("-o", "--output", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_export)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_cli.py -v`
Expected: PASS (new export cases + all existing cases).

- [ ] **Step 5: Commit**

```bash
git add history_surfer/cli.py tests/test_cli.py
git commit -m "feat(export): surfer export CLI command"
```

---

## Task 6: Selection-spec parser

**Files:**
- Create: `history_surfer/replay.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces: `parse_selection(spec, count) -> (indices, warnings)`. Grammar tokens (brackets/whitespace optional): `N`, `A-B` (inclusive), `A-` (open end), `-B` (open start `0..B`). Order preserved; duplicates kept; out-of-range → a stderr-style warning string and skip; garbage tokens → warning and skip.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay.py
"""Real tests for history_surfer.replay (selection spec + claude driving)."""
import os
import unittest


class SelectionTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay

    def sel(self, spec, count):
        return self.replay.parse_selection(spec, count)

    def test_single_and_range(self):
        idx, warn = self.sel("0,3-5", 10)
        self.assertEqual(idx, [0, 3, 4, 5])
        self.assertEqual(warn, [])

    def test_open_end(self):
        idx, warn = self.sel("5-", 8)
        self.assertEqual(idx, [5, 6, 7])
        self.assertEqual(warn, [])

    def test_open_start(self):
        idx, _ = self.sel("-2", 5)
        self.assertEqual(idx, [0, 1, 2])

    def test_order_preserved(self):
        idx, _ = self.sel("5-,0,3-4", 8)
        self.assertEqual(idx, [5, 6, 7, 0, 3, 4])

    def test_duplicates_kept(self):
        idx, _ = self.sel("2,2,2", 5)
        self.assertEqual(idx, [2, 2, 2])

    def test_brackets_and_spaces_ok(self):
        idx, _ = self.sel("[0, 3-4, 6-]", 8)
        self.assertEqual(idx, [0, 3, 4, 6, 7])

    def test_out_of_range_single_warns_and_skips(self):
        idx, warn = self.sel("99", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_range_past_end_warns_and_starts_skip(self):
        idx, warn = self.sel("10-", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_range_truncated_warns_but_keeps_valid(self):
        idx, warn = self.sel("3-100", 5)
        self.assertEqual(idx, [3, 4])
        self.assertEqual(len(warn), 1)

    def test_garbage_token_warns(self):
        idx, warn = self.sel("abc", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'history_surfer.replay'`.

- [ ] **Step 3: Write minimal implementation**

```python
# history_surfer/replay.py
"""Replay exported prompts into a Claude Code session via the `claude` CLI.

parse_selection turns a spec like "0,3-7,10-" into an ordered index list
(duplicates kept; out-of-range warns and is skipped). run_replay drives the
installed `claude` CLI headless, keeping one session across prompts.
"""

import subprocess
import uuid


def parse_selection(spec, count):
    """(indices_in_execution_order, warnings). See module docstring for grammar."""
    indices, warnings = [], []
    s = (spec or "").strip()
    if s.startswith("["):
        s = s[1:]
    if s.endswith("]"):
        s = s[:-1]
    for raw in s.split(","):
        tok = raw.strip()
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            try:
                start = int(a) if a.strip() else 0
                end = int(b) if b.strip() else count - 1
            except ValueError:
                warnings.append("invalid selection token %r" % tok)
                continue
            if start >= count:
                warnings.append(
                    "selection %r starts past last index %d" % (tok, count - 1))
                continue
            if end > count - 1:
                warnings.append(
                    "selection %r truncated at last index %d" % (tok, count - 1))
                end = count - 1
            for i in range(max(start, 0), end + 1):
                indices.append(i)
        else:
            try:
                i = int(tok)
            except ValueError:
                warnings.append("invalid selection token %r" % tok)
                continue
            if 0 <= i < count:
                indices.append(i)
            else:
                warnings.append("index %d out of range (0..%d)" % (i, count - 1))
    return indices, warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_surfer/replay.py tests/test_replay.py
git commit -m "feat(replay): selection-spec parser"
```

---

## Task 7: Index selection + `claude` argv builder

**Files:**
- Modify: `history_surfer/replay.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces:
  - `select_indices(count, select=None, first=None, last=None) -> (indices, warnings)` — `first` wins over `last` wins over `select`; default (all `None`) selects `0..count-1`.
  - `build_claude_argv(prompt_text, session_id, is_first, model=None) -> list[str]` — first prompt uses `--session-id`, later prompts use `--resume`.

- [ ] **Step 1: Write the failing test** (append a new `TestCase` to `tests/test_replay.py`)

```python
class SelectAndArgvTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay

    def test_default_selects_all(self):
        idx, warn = self.replay.select_indices(4)
        self.assertEqual(idx, [0, 1, 2, 3])
        self.assertEqual(warn, [])

    def test_first(self):
        idx, _ = self.replay.select_indices(10, first=3)
        self.assertEqual(idx, [0, 1, 2])

    def test_first_clamped(self):
        idx, _ = self.replay.select_indices(2, first=5)
        self.assertEqual(idx, [0, 1])

    def test_last(self):
        idx, _ = self.replay.select_indices(10, last=3)
        self.assertEqual(idx, [7, 8, 9])

    def test_last_clamped(self):
        idx, _ = self.replay.select_indices(2, last=5)
        self.assertEqual(idx, [0, 1])

    def test_select_delegates(self):
        idx, _ = self.replay.select_indices(8, select="5-,0")
        self.assertEqual(idx, [5, 6, 7, 0])

    def test_argv_first_uses_session_id(self):
        argv = self.replay.build_claude_argv("hello", "SID", True)
        self.assertEqual(argv, ["claude", "-p", "hello", "--session-id", "SID"])

    def test_argv_later_uses_resume(self):
        argv = self.replay.build_claude_argv("hi", "SID", False, model="claude-opus-4-8")
        self.assertEqual(
            argv, ["claude", "-p", "hi", "--resume", "SID", "--model", "claude-opus-4-8"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: FAIL — no attribute `select_indices` / `build_claude_argv`.

- [ ] **Step 3: Write minimal implementation** (append to `replay.py`)

```python
def select_indices(count, select=None, first=None, last=None):
    if first is not None:
        return list(range(0, min(first, count))), []
    if last is not None:
        return list(range(max(0, count - last), count)), []
    if select:
        return parse_selection(select, count)
    return list(range(count)), []


def build_claude_argv(prompt_text, session_id, is_first, model=None):
    argv = ["claude", "-p", prompt_text]
    argv += (["--session-id", session_id] if is_first
             else ["--resume", session_id])
    if model:
        argv += ["--model", model]
    return argv
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_surfer/replay.py tests/test_replay.py
git commit -m "feat(replay): index selection + claude argv builder"
```

---

## Task 8: Replay runner + transcript writer

**Files:**
- Modify: `history_surfer/replay.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces: `run_replay(records, indices, *, session_id=None, model=None, dry_run=False, out=None, runner=subprocess.run) -> int`. Iterates `indices` in order; builds argv (first vs. resume); in `dry_run` prints the plan and spawns nothing; otherwise calls `runner(argv, capture_output=True, text=True)`, echoes each response, and (if `out`) writes a Markdown transcript. `runner` is injectable so tests assert argv without spawning `claude`.
- `write_transcript(path, exchanges)` where `exchanges` is a list of `{index, prompt, response}`.

- [ ] **Step 1: Write the failing test** (append a new `TestCase`)

```python
class RunReplayTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay
        self.records = [{"index": i, "id": "s:%d" % i, "prompt": "p%d" % i,
                         "tags": [], "favorite": False} for i in range(4)]

    def test_dry_run_spawns_nothing(self):
        calls = []
        rc = self.replay.run_replay(
            self.records, [0, 2], dry_run=True, session_id="SID",
            runner=lambda *a, **k: calls.append(a) or _Fake(""))
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])  # dry-run never calls the runner

    def test_runner_argv_sequence_and_order(self):
        calls = []

        def fake_runner(argv, **kw):
            calls.append(argv)
            return _Fake("response for %s" % argv[2])

        rc = self.replay.run_replay(
            self.records, [1, 0, 1], session_id="SID", runner=fake_runner)
        self.assertEqual(rc, 0)
        # first call uses --session-id; subsequent use --resume; order preserved
        self.assertEqual(calls[0], ["claude", "-p", "p1", "--session-id", "SID"])
        self.assertEqual(calls[1], ["claude", "-p", "p0", "--resume", "SID"])
        self.assertEqual(calls[2], ["claude", "-p", "p1", "--resume", "SID"])

    def test_transcript_written(self):
        import tempfile
        path = tempfile.mktemp(suffix=".md")
        self.replay.run_replay(
            self.records, [0], session_id="SID", out=path,
            runner=lambda argv, **kw: _Fake("hello back"))
        with open(path, encoding="utf-8") as f:
            body = f.read()
        os.unlink(path)
        self.assertIn("p0", body)
        self.assertIn("hello back", body)


class _Fake:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: FAIL — no attribute `run_replay`.

- [ ] **Step 3: Write minimal implementation** (append to `replay.py`)

```python
import sys


def write_transcript(path, exchanges):
    from pathlib import Path
    out = ["# 🏄 Replay transcript", ""]
    for e in exchanges:
        out.append("## ▶ Prompt %d" % e["index"])
        out.append("")
        out.append(e["prompt"])
        out.append("")
        out.append("### Response")
        out.append("")
        out.append(e["response"])
        out.append("")
    Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def run_replay(records, indices, *, session_id=None, model=None,
               dry_run=False, out=None, runner=subprocess.run):
    session_id = session_id or str(uuid.uuid4())
    total = len(indices)
    exchanges = []
    for k, idx in enumerate(indices):
        rec = records[idx]
        text = rec.get("prompt") or ""
        argv = build_claude_argv(text, session_id, is_first=(k == 0), model=model)
        header = "▶ Prompt %d/%d (index %d)" % (k + 1, total, idx)
        if dry_run:
            print("%s\n  $ %s" % (header, " ".join(argv)))
            continue
        print(header, file=sys.stderr)
        result = runner(argv, capture_output=True, text=True)
        response = (getattr(result, "stdout", "") or "").rstrip()
        print(response)
        exchanges.append({"index": idx, "prompt": text, "response": response})
    if out and exchanges:
        write_transcript(out, exchanges)
        print("Wrote replay transcript to %s" % out, file=sys.stderr)
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_surfer/replay.py tests/test_replay.py
git commit -m "feat(replay): runner (injectable) + Markdown transcript"
```

---

## Task 9: CLI `replay` command

**Files:**
- Modify: `history_surfer/cli.py` (add `cmd_replay`, argparse parser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `exporter.parse_export_file`, `replay.select_indices`, `replay.run_replay`.
- Produces: `surfer replay FILE [--select S | --first N | --last N] [--dry-run] [--model M] [--session-id U] [-o FILE]`. Prints warnings to stderr; empty selection → clean no-op (rc 0, nothing spawned).

- [ ] **Step 1: Write the failing test** (append to `CliTest` in `tests/test_cli.py`)

```python
    def test_replay_dry_run_from_export(self):
        # export current project to a file, then dry-run replay it
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        rc, out = self.run_cli(["replay", path, "--dry-run", "--select", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("claude", out)
        self.assertIn("-p", out)

    def test_replay_empty_selection_is_noop(self):
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        rc, out = self.run_cli(["replay", path, "--select", "999", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertNotIn("$ claude", out)  # nothing planned/spawned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD python3 tests/test_cli.py -v`
Expected: FAIL — `replay` not a recognized command.

- [ ] **Step 3: Write minimal implementation**

In `history_surfer/cli.py`, add:

```python
def cmd_replay(args):
    from . import exporter, replay
    records = exporter.parse_export_file(args.file)
    count = len(records)
    indices, warnings = replay.select_indices(
        count, select=args.select, first=args.first, last=args.last)
    for w in warnings:
        print("warning: %s" % w, file=sys.stderr)
    if not indices:
        print("Nothing to replay (0 of %d prompts selected)." % count,
              file=sys.stderr)
        return 0
    return replay.run_replay(records, indices, session_id=args.session_id,
                             model=args.model, dry_run=args.dry_run,
                             out=args.output)
```

In `build_parser`, after the `tui` parser block, add:

```python
    sp = sub.add_parser("replay",
                        help="replay an exported file into a Claude Code session")
    sp.add_argument("file", help="a surfer-produced .json or .md export")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--select", help="e.g. 0,3-7,10- (order = execution order)")
    g.add_argument("--first", type=int, help="replay the first N prompts")
    g.add_argument("--last", type=int, help="replay the last N prompts")
    sp.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="print what would be sent; spawn nothing")
    sp.add_argument("--model", help="passthrough to `claude --model`")
    sp.add_argument("--session-id", dest="session_id",
                    help="use/resume a specific session (default: new uuid)")
    sp.add_argument("-o", "--output", help="also save the exchange to Markdown")
    sp.set_defaults(func=cmd_replay)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD python3 tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the FULL suite (regression gate)**

Run: `./run_tests.sh`
Expected: `ALL TESTS PASSED`.

- [ ] **Step 6: Commit**

```bash
git add history_surfer/cli.py tests/test_cli.py
git commit -m "feat(replay): surfer replay CLI command"
```

---

## Task 10: Live replay smoke test (one real `claude` call)

**Files:**
- Modify: `tests/test_replay.py`

**Interfaces:**
- Consumes: `replay.run_replay` with the real `subprocess.run`; the installed `claude` CLI.
- Produces: a test guarded by `CLAUDE_HISTORY_SURFER_LIVE=1` that runs two prompts through one session and asserts the second prompt can reference the first (confirms the `--session-id` → `--resume` handshake actually continues a conversation).

- [ ] **Step 1: Write the guarded live test** (append a `TestCase`)

```python
import shutil


@unittest.skipUnless(os.environ.get("CLAUDE_HISTORY_SURFER_LIVE") == "1"
                     and shutil.which("claude"),
                     "set CLAUDE_HISTORY_SURFER_LIVE=1 with claude installed")
class LiveReplayTest(unittest.TestCase):
    def test_session_continuity(self):
        from history_surfer import replay
        records = [
            {"index": 0, "prompt": "Remember the codeword BANANA. Reply 'ok'."},
            {"index": 1, "prompt": "What codeword did I ask you to remember? "
                                   "Reply with just the word."},
        ]
        captured = []
        real = __import__("subprocess").run

        def tap(argv, **kw):
            r = real(argv, **kw)
            captured.append((argv, getattr(r, "stdout", "")))
            return r

        rc = replay.run_replay(records, [0, 1], runner=tap)
        self.assertEqual(rc, 0)
        # first uses --session-id, second uses --resume (same id)
        self.assertIn("--session-id", captured[0][0])
        self.assertIn("--resume", captured[1][0])
        self.assertIn("BANANA", captured[1][1].upper())
```

- [ ] **Step 2: Run it live once, manually**

Run: `CLAUDE_HISTORY_SURFER_LIVE=1 PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: PASS — the second response contains `BANANA`, proving one continuous session. If the handshake differs on this `claude` version, adjust `build_claude_argv` (Task 7) so the second call actually resumes, then re-run Tasks 7–9 tests.

- [ ] **Step 3: Confirm it SKIPS without the env var**

Run: `PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: the live test shows `skipped`; everything else PASSES.

- [ ] **Step 4: Commit**

```bash
git add tests/test_replay.py
git commit -m "test(replay): guarded live session-continuity smoke test"
```

---

## Task 11: `dev/` folder — demo store seeder + dev README

**Files:**
- Create: `dev/seed_demo_store.py`, `dev/README.md`
- Modify: `.gitignore` (add `dev/.demo-store/`)

**Interfaces:**
- Produces: `python3 dev/seed_demo_store.py <dir>` writes a small, **fabricated** store (no real prompts/paths/secrets) under `<dir>` using the public `store` API, so media is recorded against clean example data.

- [ ] **Step 1: Write the seeder**

```python
# dev/seed_demo_store.py
"""Seed a throwaway store with fabricated prompts for screenshots/recordings.

Usage: CLAUDE_HISTORY_SURFER_DIR=<dir> python3 dev/seed_demo_store.py
Nothing here is real user data — safe to record and commit the resulting media.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from history_surfer import store  # noqa: E402

DEMO = [
    ("/Users/surfer/projects/aurora", "sess1a2b3c4d", 1,
     "Scaffold a FastAPI service with a /health endpoint and a Dockerfile.",
     "2026-06-20T14:00:00Z", ["setup"], True),
    ("/Users/surfer/projects/aurora", "sess1a2b3c4d", 2,
     "Add a vector field overlay to the plot and animate it over time.",
     "2026-06-20T14:12:00Z", ["graphics"], True),
    ("/Users/surfer/projects/aurora", "sess1a2b3c4d", 3,
     "Write a pytest that renders the animation to a PNG and checks the frame count.",
     "2026-06-20T14:30:00Z", ["testing"], False),
    ("/Users/surfer/projects/tide", "sess9f8e7d6c", 1,
     "Refactor the auth middleware to use a hard session timeout of 30 minutes.",
     "2026-06-21T09:00:00Z", ["security"], False),
    ("/Users/surfer/projects/tide", "sess9f8e7d6c", 2,
     "/model", "2026-06-21T09:05:00Z", [], False),
]


def main(dest):
    os.environ["CLAUDE_HISTORY_SURFER_DIR"] = dest
    for cwd, sess, seq, prompt, ts, tags, fav in DEMO:
        slug = store.slugify_cwd(cwd)
        store.append_prompt({"ts": ts, "session_id": sess, "cwd": cwd,
                             "project_slug": slug, "seq": seq, "prompt": prompt,
                             "is_command": prompt.startswith("/"), "text_final": True})
        for t in tags:
            store.add_overlay_event(slug, sess, seq, "tag", t)
        if fav:
            store.add_overlay_event(slug, sess, seq, "favorite", True)
    print("Seeded demo store at %s" % dest)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         os.environ.get("CLAUDE_HISTORY_SURFER_DIR", "./dev/.demo-store"))
```

- [ ] **Step 2: Verify it runs and produces browsable data**

Run:
```bash
rm -rf dev/.demo-store && python3 dev/seed_demo_store.py dev/.demo-store
CLAUDE_HISTORY_SURFER_DIR=dev/.demo-store PYTHONPATH=$PWD python3 -m history_surfer.cli list --all
```
Expected: five demo prompts listed (two ★, one `/cmd`), across `aurora` and `tide`.

- [ ] **Step 3: Write `dev/README.md`**

```markdown
# Developing claude-history-surfer

Developer notes and tooling. **None of this is needed to *use* the tool** — the
user installer never touches anything here.

## Layout
- `history_surfer/` — the package (pure Python stdlib; no pip deps).
- `tests/` — real tests (`unittest`; no mocks). Run `./run_tests.sh`.
- `docs/design.md` — architecture. `docs/superpowers/` — specs & plans.
- `dev/` — this folder: media generation + demo data.

## Running tests
```bash
./run_tests.sh                     # full suite
PYTHONPATH=$PWD python3 tests/test_replay.py -v   # one file
CLAUDE_HISTORY_SURFER_LIVE=1 ./run_tests.sh        # include the live replay call
```

## Generating the README media (screenshots + GIF)
Media is recorded against a **fabricated demo store** (`dev/seed_demo_store.py`)
so no real prompts, paths, or secrets are captured.

Dev-only dependency: [`vhs`](https://github.com/charmbracelet/vhs).
```bash
brew install vhs        # macOS; see vhs docs for Linux
./dev/generate_media.sh # seeds a temp store, records tapes → docs/media/
```
Tapes: `dev/cli.tape`, `dev/tui.tape`, `dev/export_replay.tape`.

## Architecture notes
Hybrid capture (UserPromptSubmit + Stop hooks), an append-only capture layer, and
a separate append-only curation overlay merged on read — see `docs/design.md`.
Export/replay are read-only over the store and share one normalized record shape
(`history_surfer/exporter.py`); replay drives the `claude` CLI headless
(`history_surfer/replay.py`). Full design:
`docs/superpowers/specs/2026-07-01-export-replay-readme-design.md`.
```

- [ ] **Step 4: Ignore the scratch demo store**

Add to `.gitignore`:
```
dev/.demo-store/
```

- [ ] **Step 5: Commit**

```bash
git add dev/seed_demo_store.py dev/README.md .gitignore
git commit -m "dev: demo-store seeder + developer README"
```

---

## Task 12: Media generation (vhs tapes + GIF/stills)

**Files:**
- Create: `dev/cli.tape`, `dev/tui.tape`, `dev/export_replay.tape`, `dev/generate_media.sh`
- Create: `docs/media/*.gif`, `docs/media/*.png` (generated artifacts)
- Modify: `.gitignore` (ensure `docs/media/` is **tracked**, not ignored)

**Interfaces:**
- Consumes: `vhs`, the seeder from Task 11, the `surfer` CLI.
- Produces: `./dev/generate_media.sh` → `docs/media/cli.gif`, `docs/media/tui.gif`, `docs/media/export-replay.gif` recorded from the demo store.

- [ ] **Step 1: Write `dev/cli.tape`**

```
# dev/cli.tape — recorded against $CLAUDE_HISTORY_SURFER_DIR (demo store)
Output docs/media/cli.gif
Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 18
Type "surfer list --all"      Enter    Sleep 2s
Type "surfer search vector --all"   Enter   Sleep 2s
Type "surfer show sess1a2b:2" Enter    Sleep 2s
Sleep 1s
```

- [ ] **Step 2: Write `dev/tui.tape`**

```
# dev/tui.tape
Output docs/media/tui.gif
Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 18
Type "surfer tui --all"  Enter   Sleep 2s
Down   Sleep 700ms   Down   Sleep 700ms
Enter  Sleep 2s          # detail view
Enter  Sleep 1s          # back
Type "q"  Sleep 1s
```

- [ ] **Step 3: Write `dev/export_replay.tape`**

```
# dev/export_replay.tape
Output docs/media/export-replay.gif
Set FontSize 18
Set Width 1100
Set Height 700
Set Padding 18
Type "surfer export --all --favorites -o faves.md"   Enter   Sleep 1500ms
Type "head -20 faves.md"   Enter   Sleep 2500ms
Type "surfer replay faves.md --dry-run"   Enter   Sleep 2500ms
Sleep 1s
```

- [ ] **Step 4: Write `dev/generate_media.sh`**

```bash
#!/usr/bin/env bash
# Record README media from a fabricated demo store. Requires `vhs`.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v vhs >/dev/null || { echo "install vhs first: brew install vhs"; exit 1; }

DEMO="$(mktemp -d)"
trap 'rm -rf "$DEMO"' EXIT
python3 dev/seed_demo_store.py "$DEMO"

export CLAUDE_HISTORY_SURFER_DIR="$DEMO"
export PATH="$PWD/bin:$PATH"          # use the repo's surfer without installing
mkdir -p docs/media
for tape in cli tui export_replay; do
  echo "recording $tape…"
  ( cd "$DEMO" && CLAUDE_HISTORY_SURFER_DIR="$DEMO" vhs "$OLDPWD/dev/$tape.tape" )
done
echo "wrote docs/media/*.gif"
```

Note: `bin/surfer` must run the package with the repo on `PYTHONPATH`. Verify `bin/surfer` resolves the package from the repo (it does via its shebang/sys.path); if not, prepend `PYTHONPATH="$PWD"` in the loop.

- [ ] **Step 5: Install vhs and generate the media**

Run:
```bash
brew install vhs
chmod +x dev/generate_media.sh
./dev/generate_media.sh
```
Expected: `docs/media/cli.gif`, `tui.gif`, `export-replay.gif` created.

- [ ] **Step 6: Visually verify each GIF**

Open each file and confirm: text is legible, no real user data appears, the TUI renders, export shows markers, replay dry-run prints `claude -p …` lines. (Re-run after tweaking tapes if framing is off.)

- [ ] **Step 7: Commit**

```bash
git add dev/cli.tape dev/tui.tape dev/export_replay.tape dev/generate_media.sh docs/media
git commit -m "dev: vhs tapes + generated README media"
```

---

## Task 13: README overhaul

**Files:**
- Modify: `README.md` (full rewrite)

**Interfaces:** consumes the generated media (Task 12) and the new commands (Tasks 5, 9).

- [ ] **Step 1: Replace `README.md` with the new content**

Write the file below verbatim. It: adds a 🏄 header; expands **Why**; makes **import-history the default install** (plain + clone as alternatives); embeds the GIFs; adds **Export** and **Replay** sections; and points **Development** at `dev/`.

````markdown
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

![CLI demo](docs/media/cli.gif)

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
| `surfer export [query] [--all] [--favorites] [--tag T] [--since D] [--format md\|json] [-o FILE]` | Export prompts to Markdown/JSON |
| `surfer replay <file> [--select S] [--first N] [--last N] [--dry-run] [-o FILE]` | Replay an export into a session |
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
exchange.

> **Note (v1):** replay sends prompt **text** as it was originally sent. `@file`
> references re-resolve live if those files still exist; pasted images and large
> text blobs are not re-attached.

## TUI

`surfer tui` opens an interactive browser:

![TUI demo](docs/media/tui.gif)

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
````

- [ ] **Step 2: Verify every documented command actually runs**

Run (against the demo store so it's safe/deterministic):
```bash
export CLAUDE_HISTORY_SURFER_DIR="$(mktemp -d)"
python3 dev/seed_demo_store.py "$CLAUDE_HISTORY_SURFER_DIR"
export PYTHONPATH="$PWD"
alias surfer="python3 -m history_surfer.cli"
python3 -m history_surfer.cli list --all
python3 -m history_surfer.cli search vector --all
python3 -m history_surfer.cli export --all -o /tmp/hs-check.md
python3 -m history_surfer.cli export --favorites --format json -o /tmp/hs-check.json
python3 -m history_surfer.cli replay /tmp/hs-check.md --select "0,1-2" --dry-run
python3 -m history_surfer.cli replay /tmp/hs-check.json --first 2 --dry-run
```
Expected: each exits 0; export files exist; replay prints `claude -p …` plan lines. Fix the README if any flag/name is wrong.

- [ ] **Step 3: Validate every link resolves**

Check each relative link points at a real path: `docs/media/cli.gif`,
`docs/media/tui.gif`, `docs/media/export-replay.gif`, `docs/design.md`,
`dev/README.md`, `LICENSE`. And that external URLs are well-formed:
```bash
for f in docs/media/cli.gif docs/media/tui.gif docs/media/export-replay.gif docs/design.md dev/README.md LICENSE; do
  test -e "$f" && echo "ok  $f" || echo "MISSING  $f"
done
```
Expected: all `ok`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: overhaul README (motivation, visuals, export/replay, dev pointer)"
```

---

## Task 14: Update `docs/design.md` scope

**Files:**
- Modify: `docs/design.md`

- [ ] **Step 1: Record the two features in the design doc**

In `docs/design.md` §3 (Scope), add two bullets under the capture list:

```markdown
- **Export** a selected set of prompts to a shareable file — **Markdown** (default,
  round-trippable) or **JSON** — reusing the CLI's scope/filters (`surfer export`).
- **Replay** an exported file into a fresh Claude Code session, playing prompts
  one at a time via the headless `claude` CLI, with flexible selection
  (`surfer replay`).
```

And update §10 (Future) to remove anything now delivered; leave the rest. Add a
one-line pointer near the top:

```markdown
> Export/replay design detail: `docs/superpowers/specs/2026-07-01-export-replay-readme-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/design.md
git commit -m "docs: note export/replay in the design doc"
```

---

## Task 15: Final regression + finish the branch

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `./run_tests.sh`
Expected: `ALL TESTS PASSED` (exporter, replay, cli, and all pre-existing tests).

- [ ] **Step 2: Run the live replay once, manually**

Run: `CLAUDE_HISTORY_SURFER_LIVE=1 PYTHONPATH=$PWD python3 tests/test_replay.py -v`
Expected: `LiveReplayTest` PASSES (second response contains `BANANA`).

- [ ] **Step 3: Confirm the installer is untouched by dev tooling**

Run: `grep -RIn "vhs\|dev/" install.sh history_surfer/installer.py scripts/ || echo "clean"`
Expected: `clean` — no dev references leaked into the user install path.

- [ ] **Step 4: Invoke `superpowers:finishing-a-development-branch`**

Use the finishing-a-development-branch skill to choose merge / PR / cleanup for
`feature/export-replay-readme`.

---

## Self-Review (completed before handoff)

**Spec coverage:** Export md/json (§2 → Tasks 1–5), round-trip parse (§3 → Task 4),
replay + selection semantics (§4 → Tasks 6–9), live handshake (§4.2 → Task 10),
empty-selection no-op (Tasks 8–9), dev/ + synthetic media (§7 → Tasks 11–12),
README overhaul (§6 → Task 13), design-doc update (Task 14), full testing (§8 →
Tasks throughout + Task 15). No gaps.

**Placeholder scan:** every code step contains complete code; every command has an
expected result. No TBD/TODO/"handle edge cases".

**Type consistency:** the export record shape (`index/id/ts/project/prompt/tags/
favorite/is_command/attachments`) is defined in Task 1 and consumed identically in
Tasks 2–5, 9; `parse_export_text/parse_export_file` (Task 4) are called in Tasks 9,
13; `parse_selection`/`select_indices`/`build_claude_argv`/`run_replay` signatures
match across Tasks 6–10 and the CLI in Task 9.
