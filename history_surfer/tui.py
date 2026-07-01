"""Interactive curses browser for prompt history.

The `Browser` class holds all state and performs every action against the store
(so it is fully testable without a terminal). `run()` wraps it in a thin curses
event loop that is verified manually.

Keys:
  ↑/k ↓/j  move          enter  detail / back        /  search
  f favorite  t tag       e edit ($EDITOR)            d delete   u restore
  o open attachments      a toggle all-projects       D show/hide deleted
  q quit / back
"""

import os

from . import store


class Browser:
    def __init__(self, all_projects=False):
        self.all_projects = all_projects
        self.show_deleted = False
        self.query = ""
        self.rows = []
        self.filtered = []
        self.idx = 0
        self.top = 0            # scroll offset for the list
        self.mode = "list"      # list | detail
        self.status = ""
        self.reload()

    # -- data ------------------------------------------------------------- #

    def _load(self):
        if self.all_projects:
            return store.load_all(include_deleted=self.show_deleted)
        slug = store.slugify_cwd(os.getcwd())
        return store.load_project(slug, include_deleted=self.show_deleted)

    def reload(self):
        cur = self.current()
        cur_id = cur["id"] if cur else None
        self.rows = self._load()
        self.apply_filter(keep_id=cur_id)

    def apply_filter(self, keep_id=None):
        q = self.query.lower().strip()
        if q:
            rows = [r for r in self.rows
                    if q in (r.get("prompt") or "").lower()
                    or any(q in t.lower() for t in (r.get("tags") or []))]
        else:
            rows = list(self.rows)
        # newest first for browsing
        self.filtered = list(reversed(rows))
        self.idx = 0
        if keep_id:
            for i, r in enumerate(self.filtered):
                if r["id"] == keep_id:
                    self.idx = i
                    break
        self._clamp()

    def _clamp(self):
        n = len(self.filtered)
        if n == 0:
            self.idx = 0
        else:
            self.idx = max(0, min(self.idx, n - 1))

    def current(self):
        if self.filtered and 0 <= self.idx < len(self.filtered):
            return self.filtered[self.idx]
        return None

    # -- navigation ------------------------------------------------------- #

    def move(self, delta):
        if self.filtered:
            self.idx = max(0, min(self.idx + delta, len(self.filtered) - 1))

    def set_query(self, q):
        self.query = q or ""
        self.apply_filter()

    def toggle_all_projects(self):
        self.all_projects = not self.all_projects
        self.reload()
        self.status = "scope: %s" % ("all projects" if self.all_projects else "current project")

    def toggle_show_deleted(self):
        self.show_deleted = not self.show_deleted
        self.reload()
        self.status = "deleted: %s" % ("shown" if self.show_deleted else "hidden")

    # -- actions (via overlay) ------------------------------------------- #

    def _overlay(self, op, value):
        r = self.current()
        if not r:
            return None
        store.add_overlay_event(r["project_slug"], r["session_id"], r["seq"], op, value)
        self.reload()
        return r

    def toggle_favorite(self):
        r = self.current()
        if not r:
            return
        now = not r.get("favorite")
        self._overlay("favorite", now)
        self.status = "favorited" if now else "unfavorited"

    def add_tag(self, tag):
        tag = (tag or "").strip()
        if tag:
            self._overlay("tag", tag)
            self.status = "tagged #%s" % tag

    def delete_current(self):
        if self._overlay("delete", True):
            self.status = "deleted ('u' to restore)"

    def restore_current(self):
        if self._overlay("restore", True):
            self.status = "restored"

    def set_text(self, text):
        r = self.current()
        if r and text is not None and text != r.get("prompt"):
            self._overlay("edit", text)
            self.status = "edited (original preserved)"

    def attachment_paths(self):
        r = self.current()
        if not r:
            return []
        base = store.project_dir(r["project_slug"])
        return [str(base / a["stored"]) for a in (r.get("attachments") or []) if a.get("stored")]


# --------------------------------------------------------------------------- #
# curses front-end (thin; manually verified)
# --------------------------------------------------------------------------- #

def run(all_projects=False):  # pragma: no cover - requires a terminal
    import curses
    return curses.wrapper(_main, all_projects)


def _main(stdscr, all_projects):  # pragma: no cover - requires a terminal
    import curses
    curses.curs_set(0)
    stdscr.keypad(True)
    b = Browser(all_projects)

    while True:
        _render(stdscr, b)
        try:
            c = stdscr.getch()
        except KeyboardInterrupt:
            return 0

        if b.mode == "detail":
            if c in (ord("q"), 27, ord("\n"), curses.KEY_ENTER, 10, 13):
                b.mode = "list"
            elif c in (curses.KEY_DOWN, ord("j")):
                b.move(1)
            elif c in (curses.KEY_UP, ord("k")):
                b.move(-1)
            elif c == ord("o"):
                _open_attachments(b)
            continue

        if c in (ord("q"), 27):
            return 0
        elif c in (curses.KEY_DOWN, ord("j")):
            b.move(1)
        elif c in (curses.KEY_UP, ord("k")):
            b.move(-1)
        elif c in (curses.KEY_ENTER, 10, 13):
            if b.current():
                b.mode = "detail"
        elif c == ord("/"):
            q = _prompt(stdscr, "search: ", b.query)
            b.set_query(q)
        elif c == ord("f"):
            b.toggle_favorite()
        elif c == ord("t"):
            tag = _prompt(stdscr, "tag: ", "")
            b.add_tag(tag)
        elif c == ord("d"):
            b.delete_current()
        elif c == ord("u"):
            b.restore_current()
        elif c == ord("a"):
            b.toggle_all_projects()
        elif c == ord("D"):
            b.toggle_show_deleted()
        elif c == ord("e"):
            _edit(stdscr, b)
        elif c == ord("o"):
            _open_attachments(b)


def _render(stdscr, b):  # pragma: no cover - requires a terminal
    import curses
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    scope = "all" if b.all_projects else "current"
    header = " claude-history-surfer  [%s]  %d prompt(s)%s" % (
        scope, len(b.filtered), ("  filter:%r" % b.query if b.query else ""))
    stdscr.addnstr(0, 0, header.ljust(w), w, curses.A_REVERSE)

    if b.mode == "detail":
        _render_detail(stdscr, b, h, w)
    else:
        _render_list(stdscr, b, h, w)

    help_line = ("↑↓ move  enter detail  / search  f fav  t tag  e edit  "
                 "d del  u restore  a scope  D deleted  q quit")
    stdscr.addnstr(h - 1, 0, (b.status + "   " + help_line).ljust(w)[:w - 1], w - 1,
                   curses.A_DIM)
    stdscr.refresh()


def _render_list(stdscr, b, h, w):  # pragma: no cover
    import curses
    body = h - 2
    if b.idx < b.top:
        b.top = b.idx
    elif b.idx >= b.top + body:
        b.top = b.idx - body + 1
    for i in range(body):
        ri = b.top + i
        if ri >= len(b.filtered):
            break
        r = b.filtered[ri]
        marks = ""
        if r.get("favorite"):
            marks += "*"
        if r.get("attachments"):
            marks += "@%d" % len(r["attachments"])
        if r.get("tags"):
            marks += "#" + ",".join(r["tags"])
        if r.get("deleted"):
            marks += "(del)"
        text = (r.get("prompt") or "").replace("\n", " ")
        line = "%-10s %s %s %s" % ((r.get("session_id") or "")[:8] + ":" + str(r.get("seq")),
                                   (r.get("ts") or "")[:16], marks, text)
        attr = curses.A_REVERSE if ri == b.idx else curses.A_NORMAL
        stdscr.addnstr(1 + i, 0, line.ljust(w)[:w - 1], w - 1, attr)


def _render_detail(stdscr, b, h, w):  # pragma: no cover
    r = b.current()
    if not r:
        return
    lines = [
        "id:      %s:%s" % (r.get("session_id"), r.get("seq")),
        "time:    %s" % r.get("ts"),
        "project: %s" % r.get("cwd"),
        "tags:    %s   %s" % (", ".join(r.get("tags") or []),
                              "FAVORITE" if r.get("favorite") else ""),
        "-" * (w - 1),
    ]
    for ln in (r.get("prompt") or "").splitlines() or [""]:
        lines.append(ln)
    atts = r.get("attachments") or []
    if atts:
        lines.append("-" * (w - 1))
        lines.append("attachments (press 'o' to open):")
        for a in atts:
            lines.append("  [%s] %s (%s bytes)" % (
                a.get("kind"), a.get("ref") or a.get("media_type") or a.get("name") or "",
                a.get("bytes")))
    for i, ln in enumerate(lines[: h - 2]):
        stdscr.addnstr(1 + i, 0, ln[:w - 1], w - 1)


def _prompt(stdscr, label, initial=""):  # pragma: no cover - requires a terminal
    import curses
    curses.curs_set(1)
    h, w = stdscr.getmaxyx()
    buf = list(initial)
    while True:
        stdscr.addnstr(h - 1, 0, (label + "".join(buf)).ljust(w)[:w - 1], w - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        c = stdscr.getch()
        if c in (10, 13, curses.KEY_ENTER):
            break
        elif c == 27:
            curses.curs_set(0)
            return initial
        elif c in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= c < 127:
            buf.append(chr(c))
    curses.curs_set(0)
    return "".join(buf)


def _edit(stdscr, b):  # pragma: no cover - requires a terminal
    import curses
    from . import cli
    r = b.current()
    if not r:
        return
    curses.endwin()
    new_text = cli._edit_in_editor(r.get("prompt") or "")
    if new_text is not None:
        b.set_text(new_text)
    stdscr.refresh()


def _open_attachments(b):  # pragma: no cover - requires a terminal
    import subprocess
    import sys
    paths = b.attachment_paths()
    if paths and sys.platform == "darwin":
        subprocess.call(["open"] + paths)
        b.status = "opened %d attachment(s)" % len(paths)
    elif paths:
        b.status = paths[0]
    else:
        b.status = "no attachments"
