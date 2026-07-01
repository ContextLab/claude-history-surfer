"""Real tests for the TUI Browser controller (real store, no mocks) plus a
real pty smoke test that launches the curses UI and quits."""

import os
import shutil
import tempfile
import unittest


class BrowserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-tui-")
        os.environ["CLAUDE_HISTORY_SURFER_DIR"] = os.path.join(self.tmp, "store")
        from history_surfer import store, tui
        self.store = store
        self.tui = tui
        self.cwd = "/proj/x"
        self.slug = store.slugify_cwd(self.cwd)
        for seq, text, ts in [
            (1, "first prompt about alpha", "2026-06-01T10:00:00Z"),
            (2, "second prompt about beta", "2026-06-02T10:00:00Z"),
            (3, "third prompt about alpha again", "2026-06-03T10:00:00Z"),
        ]:
            store.append_prompt({"ts": ts, "session_id": "s1", "cwd": self.cwd,
                                 "project_slug": self.slug, "seq": seq, "prompt": text,
                                 "is_command": False, "text_final": True})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CLAUDE_HISTORY_SURFER_DIR", None)

    def b(self):
        return self.tui.Browser(all_projects=True)

    def test_loads_newest_first(self):
        b = self.b()
        self.assertEqual(len(b.filtered), 3)
        self.assertEqual(b.current()["seq"], 3)   # newest at top

    def test_move_bounds(self):
        b = self.b()
        b.move(-1)
        self.assertEqual(b.idx, 0)
        b.move(1)
        b.move(1)
        self.assertEqual(b.current()["seq"], 1)
        b.move(5)
        self.assertEqual(b.idx, 2)                # clamped

    def test_filter(self):
        b = self.b()
        b.set_query("beta")
        self.assertEqual(len(b.filtered), 1)
        self.assertEqual(b.current()["seq"], 2)
        b.set_query("alpha")
        self.assertEqual(len(b.filtered), 2)

    def test_favorite_roundtrip(self):
        b = self.b()
        b.toggle_favorite()                       # favorites seq 3
        b2 = self.b()
        self.assertTrue([r for r in b2.filtered if r["seq"] == 3][0]["favorite"])

    def test_tag_and_selection_preserved(self):
        b = self.b()
        b.move(1)                                 # select seq 2
        self.assertEqual(b.current()["seq"], 2)
        b.add_tag("important")
        # after reload, selection stays on seq 2
        self.assertEqual(b.current()["seq"], 2)
        self.assertIn("important", b.current()["tags"])

    def test_delete_and_restore(self):
        b = self.b()
        target = b.current()["seq"]
        b.delete_current()
        self.assertNotIn(target, [r["seq"] for r in b.filtered])   # hidden by default
        b.toggle_show_deleted()
        self.assertIn(target, [r["seq"] for r in b.filtered])      # visible when shown
        # real usage: select the deleted row, then restore it
        b.idx = [r["seq"] for r in b.filtered].index(target)
        b.restore_current()
        b.toggle_show_deleted()                                    # hide deleted again
        self.assertIn(target, [r["seq"] for r in b.filtered])      # restored -> still visible

    def test_edit(self):
        b = self.b()
        b.set_text("edited via tui")
        self.assertEqual(b.current()["prompt"], "edited via tui")

    def test_current_project_scope_via_chdir(self):
        # Browser(all_projects=False) uses os.getcwd(); prove it scopes correctly.
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        prev = os.getcwd()
        try:
            os.chdir(other)
            b = self.tui.Browser(all_projects=False)
            self.assertEqual(len(b.filtered), 0)   # no prompts for this cwd
        finally:
            os.chdir(prev)


class TuiPtySmokeTest(unittest.TestCase):
    """Launch the real curses UI in a pseudo-terminal and quit with 'q'."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-pty-")
        self.store_dir = os.path.join(self.tmp, "store")
        from history_surfer import store
        slug = store.slugify_cwd("/p")
        os.environ["CLAUDE_HISTORY_SURFER_DIR"] = self.store_dir
        store.append_prompt({"ts": "2026-06-01T10:00:00Z", "session_id": "s1",
                             "cwd": "/p", "project_slug": slug, "seq": 1,
                             "prompt": "hello tui", "is_command": False, "text_final": True})
        os.environ.pop("CLAUDE_HISTORY_SURFER_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_launch_and_quit(self):
        import errno
        import pty
        import select
        import sys
        import time

        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ, CLAUDE_HISTORY_SURFER_DIR=self.store_dir,
                   TERM="xterm", PYTHONPATH=repo)
        argv = [sys.executable, os.path.join(repo, "bin", "surfer"), "tui", "--all"]

        pid, fd = pty.fork()
        if pid == 0:  # child
            os.execvpe(argv[0], argv, env)
            os._exit(127)

        # parent: read a little, send 'q', reap
        output = b""
        deadline = time.time() + 8
        sent_q = False
        status = None
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.3)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                except OSError as e:
                    if e.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output += chunk
            if not sent_q and len(output) > 0:
                os.write(fd, b"q")
                sent_q = True
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                break
        else:
            os.write(fd, b"q")
        if status is None:
            _, status = os.waitpid(pid, 0)

        os.close(fd)
        self.assertTrue(sent_q, "UI never produced output to drive the quit key")
        self.assertTrue(os.WIFEXITED(status), "curses UI did not exit cleanly")
        self.assertEqual(os.WEXITSTATUS(status), 0)
        self.assertIn(b"claude-history-surfer", output)
        # Colors are initialized: the header/selection use an explicit cyan bar
        # (SGR 46) rather than relying on A_REVERSE/defaults, which rendered
        # unreadably (white-on-white) on some terminals. Guards that regression.
        self.assertIn(b"\x1b[46m", output)


if __name__ == "__main__":
    unittest.main()
