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
