"""Real tests for history_surfer.transcript — real .jsonl files, real base64."""

import base64
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from history_surfer import transcript

# A fixed binary payload we base64-encode into an image block, to prove round-trip.
IMG_BYTES = bytes(range(256)) * 4  # 1024 deterministic bytes


def _line(obj):
    return json.dumps(obj) + "\n"


def user_text(text, uuid="u", meta=False, sidechain=False):
    return _line({
        "type": "user", "uuid": uuid, "isMeta": meta, "isSidechain": sidechain,
        "message": {"role": "user", "content": text},
    })


def user_blocks(blocks, uuid="u"):
    return _line({
        "type": "user", "uuid": uuid,
        "message": {"role": "user", "content": blocks},
    })


def image_block(media_type, raw):
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.b64encode(raw).decode()}}


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-tr-")
        self.path = Path(self.tmp) / "session.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, *chunks):
        with open(self.path, "a", encoding="utf-8") as f:
            for c in chunks:
                f.write(c)

    def test_parses_real_user_prompts_only(self):
        self.write(
            user_text("hello world", uuid="1"),
            user_text("<caveat>meta</caveat>", uuid="2", meta=True),
            _line({"type": "assistant", "message": {"role": "assistant", "content": "hi"}}),
            user_blocks([image_block("image/png", IMG_BYTES), {"type": "text", "text": "look at this"}], uuid="3"),
            user_blocks([{"type": "tool_result", "content": "result"}], uuid="4"),
            user_text("please read @src/foo.py and @notes.md thanks", uuid="5"),
        )
        msgs, off = transcript.parse_new(self.path, 0)
        texts = [m["text"] for m in msgs]
        self.assertEqual(texts, ["hello world", "look at this",
                                 "please read @src/foo.py and @notes.md thanks"])
        self.assertGreater(off, 0)

    def test_image_bytes_roundtrip(self):
        self.write(user_blocks([image_block("image/jpeg", IMG_BYTES),
                                {"type": "text", "text": "img"}], uuid="1"))
        msgs, _ = transcript.parse_new(self.path, 0)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(len(msgs[0]["images"]), 1)
        media_type, raw = msgs[0]["images"][0]
        self.assertEqual(media_type, "image/jpeg")
        self.assertEqual(raw, IMG_BYTES)

    def test_at_refs(self):
        self.write(user_text("check @src/foo.py and email me@x.com not @../a-b_c.txt.", uuid="1"))
        msgs, _ = transcript.parse_new(self.path, 0)
        refs = msgs[0]["at_refs"]
        self.assertIn("src/foo.py", refs)
        self.assertIn("../a-b_c.txt", refs)  # trailing period trimmed
        self.assertNotIn("x.com", refs)      # email not matched

    def test_incremental_offset(self):
        self.write(user_text("first", uuid="1"))
        msgs1, off1 = transcript.parse_new(self.path, 0)
        self.assertEqual([m["text"] for m in msgs1], ["first"])
        # nothing new yet
        msgs_none, off_same = transcript.parse_new(self.path, off1)
        self.assertEqual(msgs_none, [])
        self.assertEqual(off_same, off1)
        # append and read only the new one
        self.write(user_text("second", uuid="2"))
        msgs2, off2 = transcript.parse_new(self.path, off1)
        self.assertEqual([m["text"] for m in msgs2], ["second"])
        self.assertGreater(off2, off1)

    def test_partial_trailing_line_not_consumed(self):
        self.write(user_text("complete", uuid="1"))
        # write a partial line with NO trailing newline (simulates mid-append)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"type":"user","message":{"role":"user","content":"partial"')
        msgs, off = transcript.parse_new(self.path, 0)
        self.assertEqual([m["text"] for m in msgs], ["complete"])
        # now finish the partial line
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('}}\n')
        msgs2, off2 = transcript.parse_new(self.path, off)
        self.assertEqual([m["text"] for m in msgs2], ["partial"])

    def test_missing_file(self):
        msgs, off = transcript.parse_new(Path(self.tmp) / "nope.jsonl", 0)
        self.assertEqual(msgs, [])
        self.assertEqual(off, 0)

    def test_truncation_resets_offset(self):
        self.write(user_text("a", uuid="1"), user_text("b", uuid="2"))
        _, off = transcript.parse_new(self.path, 0)
        # offset now past end; shrink the file (rotation)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(user_text("c", uuid="3"))
        msgs, _ = transcript.parse_new(self.path, off)
        self.assertEqual([m["text"] for m in msgs], ["c"])


if __name__ == "__main__":
    unittest.main()
