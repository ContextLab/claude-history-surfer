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
