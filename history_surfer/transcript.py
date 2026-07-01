"""Parse Claude Code session transcripts, incrementally.

A transcript is a JSONL file where each line is an event. Real user prompts are
``{"type":"user","message":{"role":"user","content": <str | blocks>}}`` entries
that are not meta, not sidechain, and don't carry tool_result blocks. Pasted
images appear as ``{"type":"image","source":{"type":"base64",...}}`` blocks;
large pasted text is inlined into text blocks.

``parse_new`` reads only the bytes after a stored offset and returns complete
lines only (a trailing partial line, mid-append by Claude, is left for next time),
so enrich is idempotent and cheap even on multi-MB transcripts.
"""

import base64
import json
import re
from pathlib import Path

_AT_RE = re.compile(r"(?:^|\s)@([^\s]+)")


def _find_at_refs(text):
    refs = []
    for m in _AT_RE.finditer(text or ""):
        p = m.group(1).rstrip(".,;:)]}")
        if p:
            refs.append(p)
    return refs


def _parse_user_entry(d):
    if d.get("type") != "user":
        return None
    if d.get("isMeta") or d.get("isSidechain"):
        return None
    msg = d.get("message") or {}
    if msg.get("role") != "user":
        return None

    content = msg.get("content")
    texts, images = [], []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                texts.append(b.get("text", ""))
            elif t == "image":
                src = b.get("source") or {}
                if src.get("type") == "base64":
                    try:
                        raw = base64.b64decode(src.get("data", ""))
                    except Exception:
                        continue
                    images.append((src.get("media_type", "application/octet-stream"), raw))
            elif t == "tool_result":
                # This is a tool result turn, not a user prompt.
                return None
    else:
        return None

    text = "\n".join(t for t in texts if t)
    return {
        "uuid": d.get("uuid"),
        "text": text,
        "images": images,
        "at_refs": _find_at_refs(text),
        "timestamp": d.get("timestamp"),
    }


def parse_new(transcript_path, offset=0):
    """Return (messages, new_offset). Only complete lines are consumed."""
    path = Path(transcript_path)
    if not path.exists():
        return [], offset
    try:
        size = path.stat().st_size
    except Exception:
        return [], offset
    if offset > size:
        offset = 0  # file was truncated/rotated — reparse from the top

    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()

    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        return [], offset  # no complete line yet
    complete = data[: last_nl + 1]
    consumed = offset + len(complete)

    messages = []
    for raw in complete.split(b"\n"):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            continue
        m = _parse_user_entry(d)
        if m is not None:
            messages.append(m)
    return messages, consumed
