"""Hook orchestration: capture every prompt, enrich with attachments.

Two entry points, both wrapped so they can NEVER break the user's session:
  on_user_prompt_submit(data)  -- UserPromptSubmit: record the prompt from stdin
                                  (guarantees capture) + best-effort enrich.
  on_stop(data)                -- Stop: enrich from the now-flushed transcript
                                  (pasted images, canonical full text, @files).

Capture is from stdin (text of *every* prompt). Enrichment reads the transcript
tail (idempotent via a per-session byte offset) and reconciles each transcript
user message with its captured prompt by order among non-command prompts,
adopting the transcript's canonical text (so paste placeholders/large pastes are
finalized) and snapshotting images + @-referenced files.
"""

import traceback
from pathlib import Path

from . import config, store, transcript

PREVIEW_CHARS = 4000


# --------------------------------------------------------------------------- #
# public entry points (never raise)
# --------------------------------------------------------------------------- #

def on_user_prompt_submit(data):
    try:
        _handle_submit(data)
    except Exception as e:  # pragma: no cover - defensive
        _log_error("submit", e)


def on_stop(data):
    try:
        _handle_stop(data)
    except Exception as e:  # pragma: no cover - defensive
        _log_error("stop", e)


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #

def _handle_submit(data):
    session_id = data.get("session_id") or "unknown-session"
    cwd = data.get("cwd") or str(Path.cwd())
    prompt = data.get("prompt")
    if prompt is None:
        prompt = ""
    transcript_path = data.get("transcript_path")
    slug = store.slugify_cwd(cwd)

    seq = store.next_seq(session_id)
    rec = {
        "ts": store.now_iso(),
        "session_id": session_id,
        "cwd": cwd,
        "project_slug": slug,
        "seq": seq,
        "prompt": prompt,
        "is_command": prompt.startswith("/"),
        "text_final": False,
        "source": "stdin",
    }
    store.append_prompt(rec)

    # Best-effort: the current turn may already be in the transcript.
    if transcript_path:
        _enrich(session_id, slug, cwd, transcript_path)


def _handle_stop(data):
    session_id = data.get("session_id") or "unknown-session"
    transcript_path = data.get("transcript_path")
    cwd = data.get("cwd")
    if not transcript_path:
        return
    if not cwd:
        # Derive from the transcript location: .../projects/<slug>/<session>.jsonl
        cwd = str(Path(transcript_path).parent)
    slug = store.slugify_cwd(cwd) if data.get("cwd") else Path(transcript_path).parent.name
    _enrich(session_id, slug, cwd, transcript_path)


# --------------------------------------------------------------------------- #
# enrichment
# --------------------------------------------------------------------------- #

def _enrich(session_id, slug, cwd, transcript_path):
    st = store.read_state(session_id)
    offset = int(st.get("enrich_offset", 0))
    last_matched = int(st.get("last_matched_seq", 0))

    messages, new_offset = transcript.parse_new(transcript_path, offset)
    if not messages:
        if new_offset != offset:
            st["enrich_offset"] = new_offset
            store.write_state(session_id, st)
        return

    # Queue of captured, non-command prompt seqs awaiting a transcript match.
    records = {}
    for r in store.iter_prompt_records(slug):
        if r.get("session_id") != session_id:
            continue
        records[r.get("seq")] = r
    queue = sorted(
        s for s, r in records.items()
        if isinstance(s, int) and s > last_matched and not r.get("is_command")
    )

    qi = 0
    for msg in messages:
        if qi < len(queue):
            seq = queue[qi]
            qi += 1
        else:
            # Transcript message with no captured prompt (rare) -> synthesize one.
            seq = store.next_seq(session_id)
            store.append_prompt({
                "ts": store.now_iso(), "session_id": session_id, "cwd": cwd,
                "project_slug": slug, "seq": seq, "prompt": msg["text"],
                "is_command": False, "text_final": True, "source": "transcript",
            })
            records[seq] = {"prompt": msg["text"]}
        _finalize(slug, session_id, seq, cwd, msg, records.get(seq, {}))
        last_matched = max(last_matched, seq)

    st["enrich_offset"] = new_offset
    st["last_matched_seq"] = last_matched
    store.write_state(session_id, st)


def _resolve_ref(cwd, ref):
    p = Path(ref).expanduser()
    if not p.is_absolute():
        p = Path(cwd) / ref
    return p


def _finalize(slug, session_id, seq, cwd, msg, provisional):
    canonical = msg.get("text", "")

    # 1. images
    for media_type, raw in msg.get("images", []):
        if len(raw) > config.MAX_ATTACHMENT_BYTES:
            store.append_attachment(slug, session_id, seq, {
                "kind": "image", "media_type": media_type,
                "skipped": "too_large", "bytes": len(raw)})
            continue
        store.append_attachment(slug, session_id, seq,
                                store.store_image(slug, media_type, raw))

    # 2. @-referenced files
    for ref in msg.get("at_refs", []):
        att = store.snapshot_file(slug, "@" + ref, _resolve_ref(cwd, ref))
        if att:
            store.append_attachment(slug, session_id, seq, att)

    # 3. canonical text: finalize only if it differs from what we captured, or
    #    it is large enough to blob (keeps prompts.jsonl scannable).
    prev_text = provisional.get("prompt")
    blob = store.maybe_blob_large_text(slug, canonical)
    if blob:
        store.append_attachment(slug, session_id, seq, blob)
        prompt_field = (canonical[:PREVIEW_CHARS]
                        + "\n…[truncated; full text in attachment %s]" % blob["sha256"][:12])
        _append_final(slug, session_id, seq, cwd, prompt_field, msg.get("uuid"))
    elif canonical and canonical != prev_text:
        _append_final(slug, session_id, seq, cwd, canonical, msg.get("uuid"))


def _append_final(slug, session_id, seq, cwd, prompt_field, uuid):
    store.append_prompt({
        "ts": store.now_iso(), "session_id": session_id, "cwd": cwd,
        "project_slug": slug, "seq": seq, "prompt": prompt_field,
        "is_command": False, "text_final": True, "source": "transcript",
        "transcript_uuid": uuid,
    })


# --------------------------------------------------------------------------- #
# error logging (never surfaced to the user)
# --------------------------------------------------------------------------- #

def _log_error(where, exc):
    try:
        config.meta_dir().mkdir(parents=True, exist_ok=True)
        with open(config.errors_log(), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n%s\n" % (where, store.now_iso(), traceback.format_exc()))
    except Exception:
        pass
