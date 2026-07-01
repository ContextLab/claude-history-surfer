"""The store: append-only capture + append-only curation overlay, merged on read.

Capture files (immutable, never rewritten):
  projects/<slug>/prompts.jsonl        prompt records, keyed (session_id, seq)
  projects/<slug>/attachments.jsonl    attachment records keyed to (session_id, seq)
  projects/<slug>/attachments/<sha>.*  content-addressed blobs (dedup)

Curation file (append-only event log, latest event wins):
  projects/<slug>/overlay.jsonl        tag/untag/favorite/edit/delete/restore

Per-session state (seq counter + transcript enrich offset):
  state/<session_id>.json
"""

import datetime
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path

from . import config

# --------------------------------------------------------------------------- #
# slug + time
# --------------------------------------------------------------------------- #

def slugify_cwd(cwd):
    """Turn a working-directory path into a filesystem-safe slug.

    Mirrors Claude Code's own scheme exactly: every non-alphanumeric character
    (``/``, ``.``, space, parens, ...) becomes ``-`` (no collapsing of runs).
    This keeps live-captured prompts and imported history for the same project
    in the same folder, and aligns with ~/.claude/projects/<slug>/."""
    s = re.sub(r"[^a-zA-Z0-9]", "-", cwd or "")
    return s or "unknown"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def project_dir(slug):
    return config.projects_dir() / slug


def _paths(slug):
    d = project_dir(slug)
    return {
        "prompts": d / "prompts.jsonl",
        "attachments": d / "attachments.jsonl",
        "overlay": d / "overlay.jsonl",
        "attach_dir": d / "attachments",
    }


# --------------------------------------------------------------------------- #
# low-level jsonl IO (append is locked so concurrent sessions can't interleave)
# --------------------------------------------------------------------------- #

def _append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line + "\n")
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _read_jsonl(path):
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


# --------------------------------------------------------------------------- #
# content-addressed blob store
# --------------------------------------------------------------------------- #

_EXT_BY_MEDIA = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def ext_for_media_type(media_type):
    return _EXT_BY_MEDIA.get((media_type or "").lower(), "bin")


def store_blob(slug, data, ext):
    """Write bytes to attachments/<sha256>.<ext> (once) and return its record."""
    sha = hashlib.sha256(data).hexdigest()
    ext = (ext or "bin").lstrip(".")
    attach_dir = _paths(slug)["attach_dir"]
    attach_dir.mkdir(parents=True, exist_ok=True)
    rel = "attachments/%s.%s" % (sha, ext)
    dst = project_dir(slug) / rel
    if not dst.exists():
        tmp = dst.with_name(dst.name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
    return {"sha256": sha, "stored": rel, "bytes": len(data), "ext": ext}


def snapshot_file(slug, ref, path):
    """Snapshot a referenced file (as-sent). Returns an attachment dict or None."""
    try:
        path = Path(path)
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > config.MAX_ATTACHMENT_BYTES:
            return {"kind": "file", "ref": ref, "name": path.name,
                    "skipped": "too_large", "bytes": size}
        data = path.read_bytes()
    except Exception:
        return None
    ext = path.suffix.lstrip(".") or "bin"
    blob = store_blob(slug, data, ext)
    return {"kind": "file", "ref": ref, "name": path.name,
            "stored": blob["stored"], "sha256": blob["sha256"], "bytes": blob["bytes"]}


def store_image(slug, media_type, data):
    ext = ext_for_media_type(media_type)
    blob = store_blob(slug, data, ext)
    return {"kind": "image", "media_type": media_type,
            "stored": blob["stored"], "sha256": blob["sha256"], "bytes": blob["bytes"]}


def maybe_blob_large_text(slug, text):
    """If text is very large, store it as a text blob and return an attachment."""
    if text and len(text) > config.LARGE_TEXT_THRESHOLD:
        blob = store_blob(slug, text.encode("utf-8"), "txt")
        return {"kind": "text", "chars": len(text),
                "stored": blob["stored"], "sha256": blob["sha256"], "bytes": blob["bytes"]}
    return None


# --------------------------------------------------------------------------- #
# record appends
# --------------------------------------------------------------------------- #

def append_prompt(rec):
    _append_jsonl(_paths(rec["project_slug"])["prompts"], rec)


def append_attachment(slug, session_id, seq, att):
    rec = {"session_id": session_id, "seq": seq}
    rec.update(att)
    _append_jsonl(_paths(slug)["attachments"], rec)


def add_overlay_event(slug, session_id, seq, op, value):
    _append_jsonl(_paths(slug)["overlay"], {
        "ts": now_iso(), "session_id": session_id, "seq": seq,
        "op": op, "value": value,
    })


# --------------------------------------------------------------------------- #
# per-session state (seq + enrich offset)
# --------------------------------------------------------------------------- #

def _state_path(session_id):
    return config.state_dir() / ("%s.json" % session_id)


def read_state(session_id):
    p = _state_path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_state(session_id, st):
    config.state_dir().mkdir(parents=True, exist_ok=True)
    p = _state_path(session_id)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    os.replace(tmp, p)


def next_seq(session_id):
    st = read_state(session_id)
    seq = int(st.get("seq", 0)) + 1
    st["seq"] = seq
    write_state(session_id, st)
    return seq


# --------------------------------------------------------------------------- #
# read / merge
# --------------------------------------------------------------------------- #

def _prefer(new, cur):
    """Which of two records for the same (session, seq) wins."""
    if bool(new.get("text_final")) != bool(cur.get("text_final")):
        return bool(new.get("text_final"))
    return new.get("ts", "") >= cur.get("ts", "")


def _apply_overlay(events):
    o = {"tags": set(), "favorite": False, "edited_text": None, "deleted": False}
    for ev in sorted(events, key=lambda e: e.get("ts", "")):
        op, val = ev.get("op"), ev.get("value")
        if op == "tag":
            o["tags"].add(val)
        elif op == "untag":
            o["tags"].discard(val)
        elif op == "favorite":
            o["favorite"] = bool(val)
        elif op == "edit":
            o["edited_text"] = val
        elif op == "delete":
            o["deleted"] = bool(val)
        elif op == "restore":
            o["deleted"] = False
    return o


def load_project(slug, include_deleted=False):
    paths = _paths(slug)

    prompts = {}
    for rec in _read_jsonl(paths["prompts"]):
        key = (rec.get("session_id"), rec.get("seq"))
        cur = prompts.get(key)
        if cur is None or _prefer(rec, cur):
            prompts[key] = rec

    atts = {}
    for a in _read_jsonl(paths["attachments"]):
        key = (a.get("session_id"), a.get("seq"))
        bucket = atts.setdefault(key, [])
        sig = (a.get("sha256"), a.get("kind"), a.get("ref"))
        if sig not in [(x.get("sha256"), x.get("kind"), x.get("ref")) for x in bucket]:
            bucket.append(a)

    overlays = {}
    ev_by_key = {}
    for ev in _read_jsonl(paths["overlay"]):
        ev_by_key.setdefault((ev.get("session_id"), ev.get("seq")), []).append(ev)
    for key, evs in ev_by_key.items():
        overlays[key] = _apply_overlay(evs)

    out = []
    for key, rec in prompts.items():
        o = overlays.get(key)
        merged = dict(rec)
        merged["project_slug"] = slug
        merged["id"] = "%s:%s" % (rec.get("session_id"), rec.get("seq"))
        merged["attachments"] = atts.get(key, [])
        merged["tags"] = sorted(o["tags"]) if o else []
        merged["favorite"] = o["favorite"] if o else False
        merged["deleted"] = o["deleted"] if o else False
        if o and o.get("edited_text") is not None:
            merged["prompt_original"] = rec.get("prompt")
            merged["prompt"] = o["edited_text"]
            merged["edited"] = True
        else:
            merged["edited"] = False
        out.append(merged)

    if not include_deleted:
        out = [m for m in out if not m["deleted"]]
    out.sort(key=lambda m: (m.get("ts", ""), m.get("seq") or 0))
    return out


def iter_prompt_records(slug):
    """Raw (un-merged) prompt records for a project, in file order.

    Used by the hook to align transcript messages with captured prompts."""
    return _read_jsonl(_paths(slug)["prompts"])


def iter_slugs():
    pd = config.projects_dir()
    if not pd.exists():
        return
    for child in sorted(pd.iterdir()):
        if child.is_dir():
            yield child.name


def load_all(include_deleted=False):
    out = []
    for slug in iter_slugs():
        out.extend(load_project(slug, include_deleted))
    out.sort(key=lambda m: (m.get("ts", ""), m.get("seq") or 0))
    return out


def resolve(idstr, include_deleted=True):
    """Find prompts matching an id of the form ``session:seq`` (session may be a
    prefix). Returns a list of merged prompt dicts (usually 0 or 1)."""
    if ":" not in idstr:
        sess_part, seq_part = idstr, None
    else:
        sess_part, seq_part = idstr.rsplit(":", 1)
    matches = []
    for m in load_all(include_deleted=include_deleted):
        sid = m.get("session_id") or ""
        if not (sid == sess_part or sid.startswith(sess_part)):
            continue
        if seq_part is not None and str(m.get("seq")) != str(seq_part):
            continue
        matches.append(m)
    return matches
