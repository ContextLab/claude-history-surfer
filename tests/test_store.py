"""Real tests for history_surfer.store — actual files, temp dirs, no mocks."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-store-")
        os.environ["CLAUDE_HISTORY_SURFER_DIR"] = self.tmp
        from history_surfer import store, config
        self.store = store
        self.config = config
        self.slug = store.slugify_cwd("/Users/jmanning/proj")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CLAUDE_HISTORY_SURFER_DIR", None)

    def _prompt(self, seq, text, session="sess1", final=True, ts=None):
        return {
            "ts": ts or ("2026-06-30T21:00:%02dZ" % seq),
            "session_id": session,
            "cwd": "/Users/jmanning/proj",
            "project_slug": self.slug,
            "seq": seq,
            "prompt": text,
            "is_command": text.startswith("/"),
            "text_final": final,
        }

    def test_slug(self):
        self.assertEqual(self.store.slugify_cwd("/Users/jmanning/foo"),
                         "-Users-jmanning-foo")
        # matches Claude: every non-alphanumeric char -> '-' (dots, spaces, parens)
        self.assertEqual(self.store.slugify_cwd("/a/b.c"), "-a-b-c")
        self.assertEqual(self.store.slugify_cwd("/x/contextlab.github.io"),
                         "-x-contextlab-github-io")
        self.assertEqual(self.store.slugify_cwd("/p/Mac (2)/Desktop"),
                         "-p-Mac--2--Desktop")

    def test_append_and_load(self):
        self.store.append_prompt(self._prompt(1, "hello world"))
        loaded = self.store.load_project(self.slug)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["prompt"], "hello world")
        self.assertEqual(loaded[0]["id"], "sess1:1")
        self.assertFalse(loaded[0]["favorite"])
        self.assertEqual(loaded[0]["tags"], [])

    def test_is_noise_predicate(self):
        for t in ["<task-notification>\nx</task-notification>",
                  "[SYSTEM NOTIFICATION - NOT USER INPUT]\nfoo",
                  "<ide_opened_file>opened README</ide_opened_file>",
                  "<local-command-stdout>Set model</local-command-stdout>",
                  "[Request interrupted by user]",
                  "<command-message>history-surfer</command-message> <command-name>/x</command-name>",
                  "  <task-notification> leading whitespace"]:
            self.assertTrue(self.store.is_noise(t), t)
        # real prompts (incl. one that merely MENTIONS the tag) are not noise
        for t in ["fix the bug", "how do I parse a <task-notification> tag?",
                  "", "/model"]:
            self.assertFalse(self.store.is_noise(t), t)

    def test_load_filters_noise_by_default(self):
        self.store.append_prompt(self._prompt(1, "real one"))
        self.store.append_prompt(self._prompt(2, "<task-notification>bg</task-notification>"))
        self.assertEqual([r["prompt"] for r in self.store.load_project(self.slug)],
                         ["real one"])
        self.assertEqual(len(self.store.load_project(self.slug, include_noise=True)), 2)

    def test_prefer_text_final(self):
        # provisional (stdin) first, then finalized (transcript) — final wins
        self.store.append_prompt(self._prompt(1, "placeholder", final=False,
                                              ts="2026-06-30T21:00:00Z"))
        self.store.append_prompt(self._prompt(1, "full canonical text", final=True,
                                              ts="2026-06-30T21:00:01Z"))
        loaded = self.store.load_project(self.slug)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["prompt"], "full canonical text")

    def test_snapshot_file_dedup_and_hash(self):
        import hashlib
        src = Path(self.tmp) / "sample.py"
        payload = b"print('hi')\n"
        src.write_bytes(payload)
        a1 = self.store.snapshot_file(self.slug, "@sample.py", src)
        a2 = self.store.snapshot_file(self.slug, "@sample.py", src)
        self.assertEqual(a1["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(a1["sha256"], a2["sha256"])
        # only one blob on disk despite two snapshots
        blobs = list((self.store.project_dir(self.slug) / "attachments").glob("*.py"))
        self.assertEqual(len(blobs), 1)
        self.assertEqual(blobs[0].read_bytes(), payload)

    def test_snapshot_missing_file(self):
        self.assertIsNone(self.store.snapshot_file(self.slug, "@nope", Path(self.tmp) / "nope"))

    def test_store_image_ext(self):
        att = self.store.store_image(self.slug, "image/png", b"\x89PNG\r\n\x1a\nfake")
        self.assertEqual(att["kind"], "image")
        self.assertTrue(att["stored"].endswith(".png"))
        self.assertTrue((self.store.project_dir(self.slug) / att["stored"]).exists())

    def test_attachments_attached_to_prompt(self):
        self.store.append_prompt(self._prompt(1, "see @sample.py"))
        att = self.store.store_image(self.slug, "image/jpeg", b"jpegdata")
        self.store.append_attachment(self.slug, "sess1", 1, att)
        loaded = self.store.load_project(self.slug)
        self.assertEqual(len(loaded[0]["attachments"]), 1)
        self.assertEqual(loaded[0]["attachments"][0]["kind"], "image")

    def test_attachment_read_dedup(self):
        self.store.append_prompt(self._prompt(1, "x"))
        att = self.store.store_image(self.slug, "image/jpeg", b"jpegdata")
        # append same attachment twice (simulates enrich running twice)
        self.store.append_attachment(self.slug, "sess1", 1, att)
        self.store.append_attachment(self.slug, "sess1", 1, att)
        loaded = self.store.load_project(self.slug)
        self.assertEqual(len(loaded[0]["attachments"]), 1)

    def test_overlay_tag_favorite_edit_delete_restore(self):
        self.store.append_prompt(self._prompt(1, "original text"))
        s, slug = self.store, self.slug
        s.add_overlay_event(slug, "sess1", 1, "tag", "alpha")
        s.add_overlay_event(slug, "sess1", 1, "tag", "beta")
        s.add_overlay_event(slug, "sess1", 1, "untag", "alpha")
        s.add_overlay_event(slug, "sess1", 1, "favorite", True)
        s.add_overlay_event(slug, "sess1", 1, "edit", "edited text")
        loaded = s.load_project(slug)[0]
        self.assertEqual(loaded["tags"], ["beta"])
        self.assertTrue(loaded["favorite"])
        self.assertEqual(loaded["prompt"], "edited text")
        self.assertEqual(loaded["prompt_original"], "original text")
        self.assertTrue(loaded["edited"])
        # delete hides it by default, restore brings it back
        s.add_overlay_event(slug, "sess1", 1, "delete", True)
        self.assertEqual(len(s.load_project(slug)), 0)
        self.assertEqual(len(s.load_project(slug, include_deleted=True)), 1)
        s.add_overlay_event(slug, "sess1", 1, "restore", True)
        self.assertEqual(len(s.load_project(slug)), 1)

    def test_large_text_blob(self):
        big = "x" * (self.config.LARGE_TEXT_THRESHOLD + 10)
        att = self.store.maybe_blob_large_text(self.slug, big)
        self.assertIsNotNone(att)
        self.assertEqual(att["kind"], "text")
        blob = self.store.project_dir(self.slug) / att["stored"]
        self.assertEqual(len(blob.read_text()), len(big))
        self.assertIsNone(self.store.maybe_blob_large_text(self.slug, "small"))

    def test_seq_counter(self):
        self.assertEqual(self.store.next_seq("sessX"), 1)
        self.assertEqual(self.store.next_seq("sessX"), 2)
        self.assertEqual(self.store.next_seq("sessY"), 1)

    def test_load_all_and_resolve(self):
        self.store.append_prompt(self._prompt(1, "one"))
        other = self.store.slugify_cwd("/Users/jmanning/other")
        rec = self._prompt(1, "two")
        rec["project_slug"] = other
        rec["session_id"] = "sess2"
        rec["cwd"] = "/Users/jmanning/other"
        self.store.append_prompt(rec)
        allp = self.store.load_all()
        self.assertEqual(len(allp), 2)
        matches = self.store.resolve("sess2:1")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["prompt"], "two")
        # prefix match
        self.assertEqual(len(self.store.resolve("sess")), 2)


if __name__ == "__main__":
    unittest.main()
