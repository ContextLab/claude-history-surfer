"""One-time (idempotent) seeding from Claude Code's own ~/.claude/history.jsonl.

Each history line is ``{display, pastedContents, timestamp, project, sessionId}``.
``display`` shows paste placeholders like ``[Pasted text #1 +12 lines]``; the full
text lives in ``pastedContents["1"].content`` — we expand those back inline.

Idempotency: every entry has a stable signature (session+timestamp+display); we
remember imported signatures in ``meta/imported-history-keys`` and skip them on
re-run. Per-session ``seq`` is the stable time-ordinal within the session, and we
bump each session's live seq counter past the imported max so future live capture
never collides with imported prompts.
"""

import datetime
import hashlib
import json
import re

from . import config, store

_PASTE_RE = re.compile(r"\[Pasted text #(\d+)[^\]]*\]")


def _iso_from_ms(ms):
    try:
        dt = datetime.datetime.fromtimestamp(int(ms) / 1000.0, datetime.timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return store.now_iso()


def _expand_pastes(display, pasted):
    if not pasted:
        return display

    def repl(m):
        pid = m.group(1)
        item = pasted.get(pid) or pasted.get(int(pid) if pid.isdigit() else pid)
        if isinstance(item, dict) and item.get("content") is not None:
            return str(item["content"])
        return m.group(0)

    return _PASTE_RE.sub(repl, display or "")


def _signature(sid, ts_ms, display):
    raw = "%s|%s|%s" % (sid, ts_ms, display)
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _seen_path():
    return config.meta_dir() / "imported-history-keys"


def _load_seen():
    p = _seen_path()
    if not p.exists():
        return set()
    return set(x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip())


def _append_seen(keys):
    if not keys:
        return
    config.meta_dir().mkdir(parents=True, exist_ok=True)
    with open(_seen_path(), "a", encoding="utf-8") as f:
        for k in keys:
            f.write(k + "\n")


def import_history(path=None, verbose=False):
    path = path or config.history_jsonl()
    if not path.exists():
        if verbose:
            print("No history file at %s" % path)
        return 0

    seen = _load_seen()
    counters = {}
    session_max_seq = {}
    new_keys = []
    imported = 0

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue

            sid = d.get("sessionId") or "unknown-session"
            counters[sid] = counters.get(sid, 0) + 1
            seq = counters[sid]
            session_max_seq[sid] = max(session_max_seq.get(sid, 0), seq)

            display = d.get("display") or ""
            key = _signature(sid, d.get("timestamp"), display)
            if key in seen:
                continue

            prompt = _expand_pastes(display, d.get("pastedContents") or {})
            proj = d.get("project") or ""
            slug = store.slugify_cwd(proj)
            ts = _iso_from_ms(d.get("timestamp"))

            blob = store.maybe_blob_large_text(slug, prompt)
            if blob:
                store.append_attachment(slug, sid, seq, blob)
                prompt_field = prompt[:4000] + "\n…[truncated; full text in attachment %s]" % blob["sha256"][:12]
            else:
                prompt_field = prompt

            store.append_prompt({
                "ts": ts, "session_id": sid, "cwd": proj, "project_slug": slug,
                "seq": seq, "prompt": prompt_field,
                "is_command": prompt.startswith("/"), "text_final": True,
                "source": "history-import",
            })
            seen.add(key)
            new_keys.append(key)
            imported += 1

    _append_seen(new_keys)

    # Ensure future live capture continues past imported seqs for each session.
    for sid, mx in session_max_seq.items():
        st = store.read_state(sid)
        if int(st.get("seq", 0)) < mx:
            st["seq"] = mx
            store.write_state(sid, st)

    if verbose:
        print("Imported %d new prompt(s)." % imported)
    return imported
