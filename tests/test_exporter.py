"""Real tests for history_surfer.exporter (build/serialize/round-trip)."""
import json
import os
import tempfile
import unittest


class ExporterTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import exporter
        self.exporter = exporter

    def _rows(self):
        return [
            {"id": "sessA:1", "session_id": "sessA", "seq": 1,
             "ts": "2026-06-01T10:00:00Z", "cwd": "/proj/a",
             "prompt": "fix the vector field bug", "tags": ["graphics"],
             "favorite": True, "is_command": False,
             "attachments": [{"kind": "image", "name": None,
                              "sha256": "cd34", "bytes": 7, "stored": "attachments/cd34.png"}]},
            {"id": "sessA:2", "session_id": "sessA", "seq": 2,
             "ts": "2026-06-02T10:00:00Z", "cwd": "/proj/a",
             "prompt": "add tests for the parser", "tags": [],
             "favorite": False, "is_command": False, "attachments": []},
        ]

    def test_build_records_indexes_and_att_meta(self):
        recs = self.exporter.build_export_records(self._rows())
        self.assertEqual([r["index"] for r in recs], [0, 1])
        self.assertEqual(recs[0]["id"], "sessA:1")
        self.assertEqual(recs[0]["tags"], ["graphics"])
        self.assertTrue(recs[0]["favorite"])
        # attachment reduced to metadata only (no 'stored' path / raw bytes)
        att = recs[0]["attachments"][0]
        self.assertEqual(set(att), {"kind", "name", "sha256", "bytes"})
        self.assertEqual(att["sha256"], "cd34")

    def test_to_json_shape(self):
        recs = self.exporter.build_export_records(self._rows())
        meta = {"version": 1, "exported_at": "2026-07-01T12:00:00Z",
                "scope": "project", "filters": {"all": False}, "count": len(recs)}
        data = json.loads(self.exporter.to_json(recs, meta))
        self.assertEqual(data["surfer_export"]["version"], 1)
        self.assertEqual(data["surfer_export"]["count"], 2)
        self.assertEqual(len(data["prompts"]), 2)
        self.assertEqual(data["prompts"][0]["prompt"], "fix the vector field bug")

    def test_to_markdown_has_markers_and_text(self):
        recs = self.exporter.build_export_records(self._rows())
        meta = {"version": 1, "exported_at": "2026-07-01T12:00:00Z",
                "scope": "project", "filters": {}, "count": len(recs)}
        md = self.exporter.to_markdown(recs, meta)
        self.assertIn("# 🏄 Prompt history", md)
        self.assertIn("<!-- surfer-export version=1", md)
        self.assertIn("<!-- surfer:prompt index=0 id=sessA:1", md)
        self.assertIn("favorite=true len=24 tags=graphics -->", md)
        self.assertIn("fix the vector field bug", md)
        self.assertIn("<!-- /surfer:prompt -->", md)
        self.assertTrue(md.endswith("\n"))

    def _roundtrip_rows(self):
        return [
            {"id": "s:1", "session_id": "s", "seq": 1, "ts": "2026-06-01T10:00:00Z",
             "cwd": "/p", "prompt": "plain prompt", "tags": ["x"], "favorite": True,
             "is_command": False, "attachments": []},
            {"id": "s:2", "session_id": "s", "seq": 2, "ts": "2026-06-02T10:00:00Z",
             "cwd": "/p", "prompt": "with a fence:\n```python\nprint('hi')\n```\nend",
             "tags": [], "favorite": False, "is_command": False, "attachments": []},
            {"id": "s:3", "session_id": "s", "seq": 3, "ts": "2026-06-03T10:00:00Z",
             "cwd": "/p", "prompt": "\nleading and trailing newline\n",
             "tags": [], "favorite": False, "is_command": False, "attachments": []},
            {"id": "s:4", "session_id": "s", "seq": 4, "ts": "2026-06-04T10:00:00Z",
             "cwd": "/p", "prompt": "unicode: café ✅ 日本語", "tags": [], "favorite": False,
             "is_command": False, "attachments": []},
        ]

    def test_markdown_round_trip_is_lossless(self):
        recs = self.exporter.build_export_records(self._roundtrip_rows())
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        md = self.exporter.to_markdown(recs, meta)
        parsed = self.exporter.parse_export_text(md)
        self.assertEqual([p["prompt"] for p in parsed], [r["prompt"] for r in recs])
        self.assertEqual(parsed[0]["tags"], ["x"])
        self.assertTrue(parsed[0]["favorite"])
        self.assertFalse(parsed[1]["favorite"])
        self.assertEqual([p["index"] for p in parsed], [0, 1, 2, 3])

    def test_json_round_trip(self):
        recs = self.exporter.build_export_records(self._roundtrip_rows())
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        js = self.exporter.to_json(recs, meta)
        parsed = self.exporter.parse_export_text(js)
        self.assertEqual([p["prompt"] for p in parsed], [r["prompt"] for r in recs])

    def test_parse_export_file(self):
        recs = self.exporter.build_export_records(self._roundtrip_rows())
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as tf:
            tf.write(self.exporter.to_markdown(recs, meta))
            path = tf.name
        try:
            parsed = self.exporter.parse_export_file(path)
            self.assertEqual(len(parsed), 4)
        finally:
            os.unlink(path)

    def test_round_trip_prompt_containing_the_marker(self):
        rows = [{"id": "s:1", "session_id": "s", "seq": 1,
                 "ts": "2026-06-01T10:00:00Z", "cwd": "/p",
                 "prompt": "here is a literal marker <!-- /surfer:prompt --> in my "
                           "text\nand a fake opener <!-- surfer:prompt index=9 --> too",
                 "tags": [], "favorite": False, "is_command": False, "attachments": []}]
        recs = self.exporter.build_export_records(rows)
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": len(recs)}
        md = self.exporter.to_markdown(recs, meta)
        parsed = self.exporter.parse_export_text(md)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["prompt"], rows[0]["prompt"])

    def test_crlf_round_trip_through_file(self):
        # regression: universal-newline translation on read shrank \r\n prompts
        # below the recorded len=, corrupting the round-trip
        rows = [{"id": "s:1", "session_id": "s", "seq": 1,
                 "ts": "2026-06-01T10:00:00Z", "cwd": "/p",
                 "prompt": "windows line\r\nsecond line\rlone cr",
                 "tags": [], "favorite": False, "is_command": False,
                 "attachments": []}]
        recs = self.exporter.build_export_records(rows)
        meta = {"version": 1, "exported_at": "t", "scope": "project",
                "filters": {}, "count": 1}
        md = self.exporter.to_markdown(recs, meta)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8", newline="") as tf:
            tf.write(md)
            path = tf.name
        try:
            parsed = self.exporter.parse_export_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(parsed[0]["prompt"], rows[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
