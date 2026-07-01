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


if __name__ == "__main__":
    unittest.main()
