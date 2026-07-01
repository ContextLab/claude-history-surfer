"""Export prompts to Markdown/JSON and parse them back (the round-trip pair).

Export is read-only over the store. The Markdown format wraps each prompt's
verbatim text in HTML-comment markers so it re-imports losslessly.
"""

import json
import re
import sys
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


def to_json(records, meta):
    return json.dumps({"surfer_export": meta, "prompts": records},
                      ensure_ascii=False, indent=2, default=str)


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
        prompt = r.get("prompt") or ""
        attrs = "index=%d id=%s ts=%s favorite=%s len=%d" % (
            r["index"], r.get("id"), r.get("ts"),
            "true" if r.get("favorite") else "false", len(prompt))
        if tags:
            attrs += " tags=" + ",".join(tags)
        out.append("<!-- surfer:prompt %s -->" % attrs)
        out.append(prompt)
        out.append("<!-- /surfer:prompt -->")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


_OPEN_RE = re.compile(r"<!-- surfer:prompt (?P<attrs>[^\n]*?) -->\n")
_CLOSE = "\n<!-- /surfer:prompt -->"


def _parse_attrs(attrs):
    d = {}
    for tok in attrs.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    return d


def _record_from_attrs(d):
    idx = d.get("index", "")
    return {
        "index": int(idx) if idx.lstrip("-").isdigit() else None,
        "id": d.get("id"),
        "ts": d.get("ts"),
        "favorite": d.get("favorite") == "true",
        "tags": d["tags"].split(",") if d.get("tags") else [],
    }


def parse_export_text(text):
    """Parse a surfer-produced export (JSON or Markdown) into prompt records.

    Markdown is parsed losslessly: each opening marker carries len=<char count>,
    so the exact prompt text is sliced by length (robust to prompts that contain
    the marker text themselves). Missing len falls back to closing-marker search.
    """
    if text.lstrip().startswith("{"):
        return json.loads(text).get("prompts", [])
    records = []
    pos = 0
    while True:
        m = _OPEN_RE.search(text, pos)
        if not m:
            break
        d = _parse_attrs(m.group("attrs"))
        rec = _record_from_attrs(d)
        start = m.end()
        length_str = d.get("len", "")
        if length_str.isdigit():
            length = int(length_str)
            rec["prompt"] = text[start:start + length]
            close_at = start + length
            if text[close_at:close_at + len(_CLOSE)] != _CLOSE:
                print("warning: surfer export block (id=%s) is malformed near its "
                      "closing marker; prompt text may be inexact" % rec.get("id"),
                      file=sys.stderr)
                pos = close_at
            else:
                pos = close_at + len(_CLOSE)
        else:
            end = text.find(_CLOSE, start)
            if end == -1:
                print("warning: surfer export block (id=%s) has no closing marker; "
                      "skipping" % rec.get("id"), file=sys.stderr)
                break
            rec["prompt"] = text[start:end]
            pos = end + len(_CLOSE)
        records.append(rec)
    for i, rec in enumerate(records):
        if rec.get("index") is None:
            rec["index"] = i
    return records


def parse_export_file(path):
    return parse_export_text(Path(path).read_text(encoding="utf-8"))
