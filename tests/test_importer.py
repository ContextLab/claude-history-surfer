"""Real tests for the history importer against a temp history.jsonl."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class ImporterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-imp-")
        os.environ["CLAUDE_HISTORY_SURFER_DIR"] = os.path.join(self.tmp, "store")
        self.hist = Path(self.tmp) / "history.jsonl"
        from history_surfer import importer, store
        self.importer = importer
        self.store = store

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CLAUDE_HISTORY_SURFER_DIR", None)

    def write_hist(self, entries):
        with open(self.hist, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_import_basic_and_paste_expansion(self):
        self.write_hist([
            {"display": "first prompt", "pastedContents": {}, "timestamp": 1782800000000,
             "project": "/Users/jmanning/proj", "sessionId": "s1"},
            {"display": "look at this: [Pasted text #1 +2 lines]",
             "pastedContents": {"1": {"id": 1, "type": "text", "content": "LINE A\nLINE B"}},
             "timestamp": 1782800100000, "project": "/Users/jmanning/proj", "sessionId": "s1"},
            {"display": "/model", "pastedContents": {}, "timestamp": 1782800200000,
             "project": "/Users/jmanning/other", "sessionId": "s2"},
        ])
        n = self.importer.import_history(path=self.hist)
        self.assertEqual(n, 3)

        proj = self.store.load_project(self.store.slugify_cwd("/Users/jmanning/proj"))
        prompts = {r["seq"]: r["prompt"] for r in proj}
        self.assertEqual(prompts[1], "first prompt")
        self.assertEqual(prompts[2], "look at this: LINE A\nLINE B")   # paste expanded

        other = self.store.load_project(self.store.slugify_cwd("/Users/jmanning/other"))
        self.assertTrue(other[0]["is_command"])
        self.assertEqual(other[0]["prompt"], "/model")

    def test_idempotent(self):
        self.write_hist([
            {"display": "only prompt", "pastedContents": {}, "timestamp": 1782800000000,
             "project": "/p", "sessionId": "s1"},
        ])
        self.assertEqual(self.importer.import_history(path=self.hist), 1)
        # re-run imports nothing new
        self.assertEqual(self.importer.import_history(path=self.hist), 0)
        rows = self.store.load_project(self.store.slugify_cwd("/p"))
        self.assertEqual(len(rows), 1)

    def test_seq_bump_prevents_live_collision(self):
        self.write_hist([
            {"display": "a", "pastedContents": {}, "timestamp": 1782800000000,
             "project": "/p", "sessionId": "s1"},
            {"display": "b", "pastedContents": {}, "timestamp": 1782800100000,
             "project": "/p", "sessionId": "s1"},
        ])
        self.importer.import_history(path=self.hist)
        # a subsequent live prompt in the same session must get seq 3, not 1
        self.assertEqual(self.store.next_seq("s1"), 3)

    def test_missing_history_file(self):
        self.assertEqual(self.importer.import_history(path=Path(self.tmp) / "nope.jsonl"), 0)


if __name__ == "__main__":
    unittest.main()
