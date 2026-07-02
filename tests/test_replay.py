"""Real tests for history_surfer.replay (selection spec + claude driving)."""
import os
import shutil
import unittest


class SelectionTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay

    def sel(self, spec, count):
        return self.replay.parse_selection(spec, count)

    def test_single_and_range(self):
        idx, warn = self.sel("0,3-5", 10)
        self.assertEqual(idx, [0, 3, 4, 5])
        self.assertEqual(warn, [])

    def test_open_end(self):
        idx, warn = self.sel("5-", 8)
        self.assertEqual(idx, [5, 6, 7])
        self.assertEqual(warn, [])

    def test_open_start(self):
        idx, _ = self.sel("-2", 5)
        self.assertEqual(idx, [0, 1, 2])

    def test_order_preserved(self):
        idx, _ = self.sel("5-,0,3-4", 8)
        self.assertEqual(idx, [5, 6, 7, 0, 3, 4])

    def test_duplicates_kept(self):
        idx, _ = self.sel("2,2,2", 5)
        self.assertEqual(idx, [2, 2, 2])

    def test_brackets_and_spaces_ok(self):
        idx, _ = self.sel("[0, 3-4, 6-]", 8)
        self.assertEqual(idx, [0, 3, 4, 6, 7])

    def test_out_of_range_single_warns_and_skips(self):
        idx, warn = self.sel("99", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_range_past_end_warns_and_starts_skip(self):
        idx, warn = self.sel("10-", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_range_truncated_warns_but_keeps_valid(self):
        idx, warn = self.sel("3-100", 5)
        self.assertEqual(idx, [3, 4])
        self.assertEqual(len(warn), 1)

    def test_garbage_token_warns(self):
        idx, warn = self.sel("abc", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_reversed_range_warns_and_skips(self):
        idx, warn = self.sel("4-2", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)
        self.assertIn("reversed", warn[0])

    def test_bare_hyphen_selects_all(self):
        idx, warn = self.sel("-", 5)
        self.assertEqual(idx, [0, 1, 2, 3, 4])
        self.assertEqual(warn, [])

    def test_comma_only_selection_warns(self):
        # regression: "," used to yield 0-of-N with no warning at all
        idx, warn = self.sel(",", 5)
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)
        self.assertIn("no valid tokens", warn[0])


class SelectAndArgvTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay

    def test_default_selects_all(self):
        idx, warn = self.replay.select_indices(4)
        self.assertEqual(idx, [0, 1, 2, 3])
        self.assertEqual(warn, [])

    def test_first(self):
        idx, _ = self.replay.select_indices(10, first=3)
        self.assertEqual(idx, [0, 1, 2])

    def test_first_clamped(self):
        idx, _ = self.replay.select_indices(2, first=5)
        self.assertEqual(idx, [0, 1])

    def test_last(self):
        idx, _ = self.replay.select_indices(10, last=3)
        self.assertEqual(idx, [7, 8, 9])

    def test_last_clamped(self):
        idx, _ = self.replay.select_indices(2, last=5)
        self.assertEqual(idx, [0, 1])

    def test_select_delegates(self):
        idx, _ = self.replay.select_indices(8, select="5-,0")
        self.assertEqual(idx, [5, 6, 7, 0])

    def test_empty_select_selects_nothing_not_everything(self):
        idx, warn = self.replay.select_indices(5, select="")
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_select_none_still_selects_all(self):
        idx, warn = self.replay.select_indices(5, select=None)
        self.assertEqual(idx, [0, 1, 2, 3, 4])
        self.assertEqual(warn, [])

    def test_reversed_range_selects_nothing(self):
        idx, warn = self.replay.select_indices(5, select="4-2")
        self.assertEqual(idx, [])
        self.assertEqual(len(warn), 1)

    def test_argv_first_uses_session_id(self):
        argv = self.replay.build_claude_argv("hello", "SID", True)
        self.assertEqual(argv, ["claude", "-p", "--session-id", "SID", "--", "hello"])

    def test_argv_later_uses_resume(self):
        argv = self.replay.build_claude_argv("hi", "SID", False, model="claude-opus-4-8")
        self.assertEqual(
            argv, ["claude", "-p", "--resume", "SID", "--model", "claude-opus-4-8",
                   "--", "hi"])

    def test_prompt_starting_with_dash_is_never_a_flag(self):
        # regression: without the `--` terminator, a historical prompt like
        # "--help fix the tests" would be parsed as claude CLI flags
        argv = self.replay.build_claude_argv("--help fix the tests", "SID", True)
        self.assertEqual(argv[-2:], ["--", "--help fix the tests"])


class RunReplayTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import replay
        self.replay = replay
        self.records = [{"index": i, "id": "s:%d" % i, "prompt": "p%d" % i,
                         "tags": [], "favorite": False} for i in range(4)]

    def test_dry_run_spawns_nothing(self):
        calls = []
        rc = self.replay.run_replay(
            self.records, [0, 2], dry_run=True, session_id="SID",
            runner=lambda *a, **k: calls.append(a) or _Fake(""))
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])  # dry-run never calls the runner

    def test_runner_argv_sequence_and_order(self):
        calls = []

        def fake_runner(argv, **kw):
            calls.append(argv)
            return _Fake("response for %s" % argv[-1])

        rc = self.replay.run_replay(
            self.records, [1, 0, 1], session_id="SID", runner=fake_runner)
        self.assertEqual(rc, 0)
        # first call uses --session-id; subsequent use --resume; order preserved
        self.assertEqual(calls[0], ["claude", "-p", "--session-id", "SID", "--", "p1"])
        self.assertEqual(calls[1], ["claude", "-p", "--resume", "SID", "--", "p0"])
        self.assertEqual(calls[2], ["claude", "-p", "--resume", "SID", "--", "p1"])

    def test_nonzero_returncode_aborts_replay(self):
        # a failed claude call must abort (later prompts depend on the session)
        # and surface a nonzero exit code — not continue silently
        import io
        from contextlib import redirect_stderr
        calls = []

        def failing_runner(argv, **kw):
            calls.append(argv)
            f = _Fake("")
            f.returncode = 2
            f.stderr = "session not found"
            return f

        err = io.StringIO()
        with redirect_stderr(err):
            rc = self.replay.run_replay(
                self.records, [0, 1, 2], session_id="SID", runner=failing_runner)
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)   # aborted after the first failure
        self.assertIn("session not found", err.getvalue())

    def test_missing_claude_binary_clean_error(self):
        import io
        from contextlib import redirect_stderr

        def no_claude(argv, **kw):
            raise FileNotFoundError("claude")

        err = io.StringIO()
        with redirect_stderr(err):
            rc = self.replay.run_replay(
                self.records, [0], session_id="SID", runner=no_claude)
        self.assertEqual(rc, 1)
        self.assertIn("not found", err.getvalue())

    def test_transcript_written(self):
        import tempfile
        path = tempfile.mktemp(suffix=".md")
        self.replay.run_replay(
            self.records, [0], session_id="SID", out=path,
            runner=lambda argv, **kw: _Fake("hello back"))
        with open(path, encoding="utf-8") as f:
            body = f.read()
        os.unlink(path)
        self.assertIn("p0", body)
        self.assertIn("hello back", body)


class _Fake:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


@unittest.skipUnless(os.environ.get("CLAUDE_HISTORY_SURFER_LIVE") == "1"
                     and shutil.which("claude"),
                     "set CLAUDE_HISTORY_SURFER_LIVE=1 with claude installed")
class LiveReplayTest(unittest.TestCase):
    def test_session_continuity(self):
        from history_surfer import replay
        records = [
            {"index": 0, "prompt": "Remember the codeword BANANA. Reply 'ok'."},
            {"index": 1, "prompt": "What codeword did I ask you to remember? "
                                   "Reply with just the word."},
        ]
        captured = []
        real = __import__("subprocess").run

        def tap(argv, **kw):
            r = real(argv, **kw)
            captured.append((argv, getattr(r, "stdout", "")))
            return r

        rc = replay.run_replay(records, [0, 1], runner=tap)
        self.assertEqual(rc, 0)
        # first uses --session-id, second uses --resume (same id)
        self.assertIn("--session-id", captured[0][0])
        self.assertIn("--resume", captured[1][0])
        self.assertIn("BANANA", captured[1][1].upper())


if __name__ == "__main__":
    unittest.main()
