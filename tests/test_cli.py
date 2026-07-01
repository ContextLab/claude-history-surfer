"""Real tests for the CLI (history_surfer.cli) against a populated temp store."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-cli-")
        os.environ["CLAUDE_HISTORY_SURFER_DIR"] = self.tmp
        from history_surfer import store, cli
        self.store = store
        self.cli = cli
        self._seed()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CLAUDE_HISTORY_SURFER_DIR", None)

    def _add(self, cwd, session, seq, prompt, ts):
        slug = self.store.slugify_cwd(cwd)
        self.store.append_prompt({
            "ts": ts, "session_id": session, "cwd": cwd, "project_slug": slug,
            "seq": seq, "prompt": prompt, "is_command": prompt.startswith("/"),
            "text_final": True})
        return slug

    def _seed(self):
        self.slug_a = self._add("/proj/a", "sessA", 1, "fix the vector field bug", "2026-06-01T10:00:00Z")
        self._add("/proj/a", "sessA", 2, "add tests for the parser", "2026-06-02T10:00:00Z")
        self._add("/proj/a", "sessA", 3, "/model", "2026-06-03T10:00:00Z")
        self.slug_b = self._add("/proj/b", "sessB", 1, "unrelated project prompt", "2026-06-04T10:00:00Z")
        # attach an image to sessA:1
        att = self.store.store_image(self.slug_a, "image/png", b"pngdata")
        self.store.append_attachment(self.slug_a, "sessA", 1, att)

    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.cli.main(argv)
        return rc, buf.getvalue()

    def test_search_substring_current_project_default(self):
        # default scope = cwd; force project explicitly for determinism
        rc, out = self.run_cli(["search", "vector", "--project", "/proj/a"])
        self.assertEqual(rc, 0)
        self.assertIn("vector field", out)
        self.assertNotIn("unrelated", out)

    def test_search_all_projects(self):
        rc, out = self.run_cli(["search", "prompt", "--all"])
        self.assertIn("unrelated project prompt", out)

    def test_search_case_insensitive(self):
        _, out = self.run_cli(["search", "VECTOR", "--project", "/proj/a"])
        self.assertIn("vector field", out)

    def test_search_regex(self):
        _, out = self.run_cli(["search", r"add tests?", "--regex", "--project", "/proj/a"])
        self.assertIn("add tests", out)

    def test_search_json(self):
        _, out = self.run_cli(["search", "vector", "--project", "/proj/a", "--json"])
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["seq"], 1)
        self.assertEqual(len(data[0]["attachments"]), 1)

    def test_list_limit(self):
        _, out = self.run_cli(["list", "--all", "--limit", "2"])
        # 2 most recent rows only
        self.assertEqual(out.strip().count("\n"), 1)

    def test_show(self):
        _, out = self.run_cli(["show", "sessA:1"])
        self.assertIn("fix the vector field bug", out)
        self.assertIn("attachments:", out)
        self.assertIn("image", out)

    def test_stats_all(self):
        rc, out = self.run_cli(["stats", "--all"])
        self.assertEqual(rc, 0)
        self.assertIn("-proj-a", out)
        self.assertIn("-proj-b", out)

    def test_stats_current_project_default(self):
        # default scope = current project; force one for determinism
        rc, out = self.run_cli(["stats", "--project", "/proj/a"])
        self.assertEqual(rc, 0)
        self.assertIn("-proj-a", out)
        self.assertNotIn("-proj-b", out)

    def test_favorite_and_filter(self):
        rc, _ = self.run_cli(["favorite", "sessA:2"])
        self.assertEqual(rc, 0)
        _, out = self.run_cli(["list", "--all", "--favorites"])
        self.assertIn("add tests", out)
        self.assertNotIn("vector field", out)

    def test_tag_and_filter(self):
        self.run_cli(["tag", "sessA:1", "graphics"])
        # tag-only filtering is `list --tag`
        _, out = self.run_cli(["list", "--all", "--tag", "graphics"])
        self.assertIn("vector field", out)
        self.assertNotIn("add tests", out)
        # `search` ANDs query with tag: matching query + tag -> hit
        _, out2 = self.run_cli(["search", "vector", "--project", "/proj/a", "--tag", "graphics"])
        self.assertIn("vector field", out2)
        # non-matching query + tag -> no hit (AND semantics)
        _, out3 = self.run_cli(["search", "nomatch", "--project", "/proj/a", "--tag", "graphics"])
        self.assertNotIn("vector field", out3)
        # searching the tag text itself also works
        _, out4 = self.run_cli(["search", "graphics", "--project", "/proj/a"])
        self.assertIn("vector field", out4)

    def test_edit_with_text(self):
        rc, _ = self.run_cli(["edit", "sessA:1", "--text", "rewritten prompt"])
        self.assertEqual(rc, 0)
        _, out = self.run_cli(["show", "sessA:1"])
        self.assertIn("rewritten prompt", out)
        self.assertIn("original preserved", out)

    def test_delete_and_restore(self):
        self.run_cli(["delete", "sessA:2"])
        _, out = self.run_cli(["list", "--all"])
        self.assertNotIn("add tests", out)
        self.run_cli(["restore", "sessA:2"])
        _, out2 = self.run_cli(["list", "--all"])
        self.assertIn("add tests", out2)

    def test_open_prints_attachment_path(self):
        rc, out = self.run_cli(["open", "sessA:1"])
        self.assertEqual(rc, 0)
        self.assertIn("attachments/", out)
        # the printed path really exists
        printed = out.strip().splitlines()[0]
        self.assertTrue(os.path.exists(printed))

    def test_show_unknown_id(self):
        rc, _ = self.run_cli(["show", "nope:9"])
        self.assertEqual(rc, 1)

    def test_export_markdown_stdout(self):
        rc, out = self.run_cli(["export", "--project", "/proj/a"])
        self.assertEqual(rc, 0)
        self.assertIn("<!-- surfer:prompt", out)
        self.assertIn("fix the vector field bug", out)

    def test_export_json_to_file(self):
        path = os.path.join(self.tmp, "out.json")
        rc, _ = self.run_cli(["export", "--project", "/proj/a",
                              "--format", "json", "-o", path])
        self.assertEqual(rc, 0)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["surfer_export"]["scope"], "project")
        self.assertGreaterEqual(data["surfer_export"]["count"], 3)

    def test_export_respects_filters(self):
        self.run_cli(["favorite", "sessA:1"])
        rc, out = self.run_cli(["export", "--project", "/proj/a", "--favorites"])
        self.assertEqual(rc, 0)
        self.assertIn("fix the vector field bug", out)
        self.assertNotIn("add tests for the parser", out)

    def test_replay_dry_run_from_export(self):
        # export current project to a file, then dry-run replay it
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        rc, out = self.run_cli(["replay", path, "--dry-run", "--select", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("claude", out)
        self.assertIn("-p", out)

    def test_replay_empty_selection_is_noop(self):
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        rc, out = self.run_cli(["replay", path, "--select", "999", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertNotIn("$ claude", out)  # nothing planned/spawned

    def test_replay_empty_selection_prints_message(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = self.cli.main(["replay", path, "--select", "999", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("Nothing to replay", err_buf.getvalue())

    def test_replay_dry_run_passes_session_and_model(self):
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        rc, out = self.run_cli(["replay", path, "--select", "0", "--dry-run",
                                "--session-id", "MYSID", "--model", "claude-opus-4-8"])
        self.assertEqual(rc, 0)
        self.assertIn("MYSID", out)
        self.assertIn("claude-opus-4-8", out)

    def test_replay_select_and_first_mutually_exclusive(self):
        import io
        from contextlib import redirect_stderr
        path = os.path.join(self.tmp, "e.json")
        self.run_cli(["export", "--project", "/proj/a", "--format", "json", "-o", path])
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.cli.main(["replay", path, "--select", "0", "--first", "1"])


if __name__ == "__main__":
    unittest.main()
