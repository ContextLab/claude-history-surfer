"""`surfer` command-line interface.

Search, list, show, stats, import history, curate (tag/favorite/edit/delete),
open attachments, and launch the TUI. Curation goes through the store's
append-only overlay, so captured data is never mutated in place.
"""

import argparse
import os
import subprocess
import sys

from . import store


# --------------------------------------------------------------------------- #
# selection + filtering
# --------------------------------------------------------------------------- #

def _rows_for(args):
    include_deleted = getattr(args, "include_deleted", False)
    if getattr(args, "all", False):
        return store.load_all(include_deleted=include_deleted)
    proj = getattr(args, "project", None)
    slug = store.slugify_cwd(os.path.abspath(proj) if proj else os.getcwd())
    return store.load_project(slug, include_deleted=include_deleted)


def _filter(rows, query=None, regex=False, favorites=False, tag=None, since=None):
    out = rows
    if favorites:
        out = [r for r in out if r.get("favorite")]
    if tag:
        out = [r for r in out if tag in (r.get("tags") or [])]
    if since:
        out = [r for r in out if (r.get("ts") or "") >= since]
    if query:
        if regex:
            import re
            rx = re.compile(query, re.IGNORECASE)
            out = [r for r in out if rx.search(r.get("prompt") or "")]
        else:
            q = query.lower()
            out = [r for r in out if q in (r.get("prompt") or "").lower()
                   or any(q in t.lower() for t in (r.get("tags") or []))]
    return out


def _scope_hint(args, rows, **filter_kw):
    """When a project-scoped command matches nothing but --all would match,
    say so on stderr instead of leaving a silently empty result."""
    if rows or getattr(args, "all", False):
        return
    try:
        n = len(_filter(store.load_all(
            include_deleted=getattr(args, "include_deleted", False)), **filter_kw))
    except Exception:
        return
    if n:
        print("0 match(es) in this project, but %d across all projects — "
              "add --all to widen the search." % n, file=sys.stderr)


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #

def _short_id(row):
    sid = row.get("session_id") or ""
    return "%s:%s" % (sid[:8], row.get("seq"))


def _one_line(row):
    prompt = (row.get("prompt") or "").replace("\n", " ")
    if len(prompt) > 90:
        prompt = prompt[:87] + "..."
    marks = []
    if row.get("favorite"):
        marks.append("★")
    if row.get("attachments"):
        marks.append("📎%d" % len(row["attachments"]))
    if row.get("tags"):
        marks.append("#" + ",".join(row["tags"]))
    if row.get("is_command"):
        marks.append("/cmd")
    if row.get("deleted"):
        marks.append("(deleted)")
    tail = ("  " + " ".join(marks)) if marks else ""
    return "%-11s %s  %s%s" % (_short_id(row), (row.get("ts") or "")[:19], prompt, tail)


def _print_rows(rows, limit=None):
    if limit:
        rows = rows[-limit:]
    for r in rows:
        print(_one_line(r))
    print("\n%d prompt(s)." % len(rows), file=sys.stderr)


def _print_full(row):
    print("id:        %s:%s" % (row.get("session_id"), row.get("seq")))
    print("time:      %s" % row.get("ts"))
    print("project:   %s" % row.get("cwd"))
    if row.get("favorite"):
        print("favorite:  yes")
    if row.get("tags"):
        print("tags:      %s" % ", ".join(row["tags"]))
    if row.get("edited"):
        print("edited:    yes (original preserved)")
    if row.get("deleted"):
        print("deleted:   yes")
    print("-" * 60)
    print(row.get("prompt") or "")
    atts = row.get("attachments") or []
    if atts:
        print("-" * 60)
        print("attachments:")
        base = store.project_dir(row["project_slug"])
        for a in atts:
            if a.get("skipped"):
                print("  - [%s] %s (skipped: %s, %s bytes)"
                      % (a.get("kind"), a.get("ref") or a.get("media_type") or "",
                         a["skipped"], a.get("bytes")))
            else:
                print("  - [%s] %s  (%s bytes)  %s"
                      % (a.get("kind"), a.get("ref") or a.get("media_type") or a.get("name") or "",
                         a.get("bytes"), base / a.get("stored", "")))


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_search(args):
    rows = _filter(_rows_for(args), query=args.query, regex=args.regex,
                   favorites=args.favorites, tag=args.tag, since=args.since)
    _scope_hint(args, rows, query=args.query, regex=args.regex,
                favorites=args.favorites, tag=args.tag, since=args.since)
    if args.json:
        import json
        print(json.dumps(rows[-args.limit:] if args.limit else rows,
                         ensure_ascii=False, indent=2, default=str))
    else:
        _print_rows(rows, args.limit)
    return 0


def cmd_list(args):
    rows = _filter(_rows_for(args), favorites=args.favorites, tag=args.tag)
    _scope_hint(args, rows, favorites=args.favorites, tag=args.tag)
    if args.json:
        import json
        print(json.dumps(rows[-args.limit:] if args.limit else rows,
                         ensure_ascii=False, indent=2, default=str))
    else:
        _print_rows(rows, args.limit)
    return 0


def _resolve_one(idstr):
    matches = store.resolve(idstr)
    if not matches:
        print("No prompt matches id %r" % idstr, file=sys.stderr)
        return None
    if len(matches) > 1:
        print("Ambiguous id %r matches %d prompts; be more specific:" % (idstr, len(matches)),
              file=sys.stderr)
        for m in matches[:10]:
            print("  " + _one_line(m), file=sys.stderr)
        return None
    return matches[0]


def cmd_show(args):
    row = _resolve_one(args.id)
    if not row:
        return 1
    if args.json:
        import json
        print(json.dumps(row, ensure_ascii=False, indent=2, default=str))
    else:
        _print_full(row)
    return 0


def cmd_stats(args):
    if getattr(args, "all", False):
        slugs = list(store.iter_slugs())
    else:
        proj = getattr(args, "project", None)
        slugs = [store.slugify_cwd(os.path.abspath(proj) if proj else os.getcwd())]
    total = 0
    per = []
    for slug in slugs:
        rows = store.load_project(slug, include_deleted=True)
        live = [r for r in rows if not r.get("deleted")]
        favs = [r for r in live if r.get("favorite")]
        atts = sum(len(r.get("attachments") or []) for r in live)
        dates = sorted((r.get("ts") or "")[:10] for r in live if r.get("ts"))
        span = ("%s..%s" % (dates[0], dates[-1])) if dates else "—"
        per.append((slug, len(live), len(favs), atts, span))
        total += len(live)
    per.sort(key=lambda t: -t[1])
    for slug, n, favs, atts, span in per:
        print("%6d  %-21s  %s  (%d ★, %d 📎)" % (n, span, slug, favs, atts))
    if getattr(args, "all", False):
        scope = "%d project(s)" % len(per)
    elif getattr(args, "project", None):
        scope = "project %s" % slugs[0]
    else:
        scope = "current project"
    print("\n%d prompt(s) across %s." % (total, scope), file=sys.stderr)
    return 0


def _curate(idstr, op, value):
    row = _resolve_one(idstr)
    if not row:
        return 1
    store.add_overlay_event(row["project_slug"], row["session_id"], row["seq"], op, value)
    return 0


def cmd_tag(args):
    return _curate(args.id, "tag", args.value)


def cmd_untag(args):
    return _curate(args.id, "untag", args.value)


def cmd_favorite(args):
    return _curate(args.id, "favorite", True)


def cmd_unfavorite(args):
    return _curate(args.id, "favorite", False)


def cmd_delete(args):
    return _curate(args.id, "delete", True)


def cmd_restore(args):
    return _curate(args.id, "restore", True)


def cmd_edit(args):
    row = _resolve_one(args.id)
    if not row:
        return 1
    if args.text is not None:
        new_text = args.text
    else:
        new_text = _edit_in_editor(row.get("prompt") or "")
        if new_text is None:
            print("Edit cancelled (no change).", file=sys.stderr)
            return 1
    store.add_overlay_event(row["project_slug"], row["session_id"], row["seq"], "edit", new_text)
    return 0


def _edit_in_editor(initial):
    import tempfile
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(initial)
        path = tf.name
    try:
        subprocess.call([editor, path])
        with open(path, "r", encoding="utf-8") as f:
            new_text = f.read()
    finally:
        os.unlink(path)
    if new_text == initial:
        return None
    return new_text


def cmd_open(args):
    row = _resolve_one(args.id)
    if not row:
        return 1
    base = store.project_dir(row["project_slug"])
    paths = [str(base / a["stored"]) for a in (row.get("attachments") or []) if a.get("stored")]
    if not paths:
        print("No attachments for %s" % args.id, file=sys.stderr)
        return 1
    for p in paths:
        print(p)
    if args.reveal and sys.platform == "darwin":
        subprocess.call(["open"] + paths)
    return 0


def cmd_import(args):
    from . import importer
    n = importer.import_history(verbose=True)
    print("Imported %d prompt(s) from history.jsonl." % n)
    return 0


def cmd_tui(args):
    from . import tui
    return tui.run(all_projects=args.all)


def cmd_replay(args):
    from . import exporter, replay
    try:
        records = exporter.parse_export_file(args.file)
    except FileNotFoundError:
        print("Error: no such file: %s" % args.file, file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print("Error: could not parse %s as a surfer export (%s)"
              % (args.file, exc), file=sys.stderr)
        return 1
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        print("Error: %s is not a surfer export (no prompts found)" % args.file,
              file=sys.stderr)
        return 1
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
        out_path = Path(args.output)
        if not out_path.parent.exists():
            print("Error: directory %r does not exist" % str(out_path.parent),
                  file=sys.stderr)
            return 1
        try:
            # newline="" keeps \r in prompts intact so the export re-imports
            # byte-identical (universal newlines would break the len= guard).
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError as exc:
            print("Error: could not write %r (%s)" % (args.output, exc),
                  file=sys.stderr)
            return 1
        print("Exported %d prompt(s) to %s" % (len(records), args.output),
              file=sys.stderr)
    else:
        print(text)
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(prog="surfer",
                                description="Surf your Claude Code prompt history.")
    sub = p.add_subparsers(dest="cmd")

    def add_scope(sp):
        sp.add_argument("--all", action="store_true", help="all projects (default: current)")
        sp.add_argument("--project", help="a specific project path")
        sp.add_argument("--include-deleted", action="store_true", dest="include_deleted")

    sp = sub.add_parser("search", help="search prompts")
    sp.add_argument("query")
    add_scope(sp)
    sp.add_argument("--regex", action="store_true")
    sp.add_argument("--favorites", action="store_true")
    sp.add_argument("--tag")
    sp.add_argument("--since", help="ISO date, e.g. 2026-06-01")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

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

    sp = sub.add_parser("list", help="list recent prompts")
    add_scope(sp)
    sp.add_argument("--favorites", action="store_true")
    sp.add_argument("--tag")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="show one prompt in full")
    sp.add_argument("id")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("stats", help="prompt counts (current project; --all for every project)")
    add_scope(sp)
    sp.set_defaults(func=cmd_stats)

    for name, fn, needs_val in [
        ("tag", cmd_tag, True), ("untag", cmd_untag, True),
        ("favorite", cmd_favorite, False), ("unfavorite", cmd_unfavorite, False),
        ("delete", cmd_delete, False), ("restore", cmd_restore, False),
    ]:
        sp = sub.add_parser(name, help="%s a prompt" % name)
        sp.add_argument("id")
        if needs_val:
            sp.add_argument("value")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("edit", help="edit a prompt's text (overlay; original kept)")
    sp.add_argument("id")
    sp.add_argument("--text", help="new text (default: open $EDITOR)")
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("open", help="print/reveal a prompt's attachment paths")
    sp.add_argument("id")
    sp.add_argument("--reveal", action="store_true", help="open with the OS (macOS)")
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("import-history", help="seed from ~/.claude/history.jsonl")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("tui", help="launch the interactive browser")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_tui)

    sp = sub.add_parser("replay",
                        help="replay an exported file into a Claude Code session")
    sp.add_argument("file", help="a surfer-produced .json or .md export")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--select",
                   help="e.g. 0,3-7,10- (order = execution order); "
                        "bare '-' selects all; empty string selects none")
    g.add_argument("--first", type=int, help="replay the first N prompts")
    g.add_argument("--last", type=int, help="replay the last N prompts")
    sp.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="print what would be sent; spawn nothing")
    sp.add_argument("--model", help="passthrough to `claude --model`")
    sp.add_argument("--session-id", dest="session_id",
                    help="use/resume a specific session (default: new uuid)")
    sp.add_argument("-o", "--output", help="also save the exchange to Markdown")
    sp.set_defaults(func=cmd_replay)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
