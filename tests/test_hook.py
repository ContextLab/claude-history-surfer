"""Real tests for the hook orchestration (history_surfer.hook) + entry scripts."""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def line(obj):
    return json.dumps(obj) + "\n"


def u_text(text, uuid="u"):
    return line({"type": "user", "uuid": uuid,
                 "message": {"role": "user", "content": text}})


def u_blocks(blocks, uuid="u"):
    return line({"type": "user", "uuid": uuid,
                 "message": {"role": "user", "content": blocks}})


def img_block(media_type, raw):
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.b64encode(raw).decode()}}


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hs-hook-")
        self.data_dir = os.path.join(self.tmp, "store")
        self.cwd = os.path.join(self.tmp, "proj")
        os.makedirs(self.cwd)
        os.environ["CLAUDE_HISTORY_SURFER_DIR"] = self.data_dir
        self.transcript = os.path.join(self.tmp, "session.jsonl")
        from history_surfer import hook, store
        self.hook = hook
        self.store = store
        self.slug = store.slugify_cwd(self.cwd)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CLAUDE_HISTORY_SURFER_DIR", None)

    def submit(self, prompt, session="s1"):
        self.hook.on_user_prompt_submit({
            "session_id": session, "cwd": self.cwd, "prompt": prompt,
            "transcript_path": self.transcript, "hook_event_name": "UserPromptSubmit"})

    def stop(self, session="s1"):
        self.hook.on_stop({"session_id": session, "cwd": self.cwd,
                           "transcript_path": self.transcript, "hook_event_name": "Stop"})

    def write_transcript(self, *chunks):
        with open(self.transcript, "a", encoding="utf-8") as f:
            for c in chunks:
                f.write(c)

    def loaded(self, session="s1"):
        return self.store.load_project(self.slug, include_deleted=True)

    # --- scenarios -------------------------------------------------------- #

    def test_simple_prompt(self):
        self.submit("hello")                 # transcript empty at submit
        self.write_transcript(u_text("hello", uuid="1"))
        self.stop()
        rows = self.loaded()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt"], "hello")
        self.assertEqual(rows[0]["attachments"], [])

    def test_pasted_image_captured(self):
        payload = bytes(range(256)) * 3
        self.submit("look at this")
        self.write_transcript(u_blocks([img_block("image/jpeg", payload),
                                        {"type": "text", "text": "look at this"}], uuid="1"))
        self.stop()
        row = self.loaded()[0]
        self.assertEqual(len(row["attachments"]), 1)
        att = row["attachments"][0]
        self.assertEqual(att["kind"], "image")
        stored = self.store.project_dir(self.slug) / att["stored"]
        self.assertEqual(stored.read_bytes(), payload)

    def test_large_paste_canonical_text_adopted(self):
        full = "see this: " + ("DATA " * 50)
        self.submit("see this: [Pasted text #1 +5 lines]")   # stdin placeholder
        self.write_transcript(u_text(full, uuid="1"))
        self.stop()
        row = self.loaded()[0]
        self.assertEqual(row["prompt"], full)   # transcript text won

    def test_at_file_snapshot(self):
        import hashlib
        sub = Path(self.cwd) / "sub"
        sub.mkdir()
        f = sub / "f.txt"
        f.write_text("file body")
        self.submit("please read @sub/f.txt")
        self.write_transcript(u_text("please read @sub/f.txt", uuid="1"))
        self.stop()
        atts = self.loaded()[0]["attachments"]
        files = [a for a in atts if a["kind"] == "file"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["sha256"], hashlib.sha256(b"file body").hexdigest())

    def test_slash_command_logged_not_filtered(self):
        self.submit("/model")                # commands never enter transcript as prompts
        rows = self.loaded()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_command"])
        self.assertEqual(rows[0]["prompt"], "/model")

    def test_idempotent_stop(self):
        payload = b"imgbytes"
        self.submit("look")
        self.write_transcript(u_blocks([img_block("image/png", payload),
                                        {"type": "text", "text": "look"}], uuid="1"))
        self.stop()
        self.stop()   # second flush must not duplicate
        row = self.loaded()[0]
        self.assertEqual(len(row["attachments"]), 1)

    def test_multiple_prompts_align(self):
        self.submit("first")
        self.write_transcript(u_text("first", uuid="1"))
        self.stop()
        self.submit("second with @sub/x.txt")
        (Path(self.cwd) / "sub").mkdir(exist_ok=True)
        (Path(self.cwd) / "sub" / "x.txt").write_text("xx")
        self.write_transcript(u_text("second with @sub/x.txt", uuid="2"))
        self.stop()
        rows = sorted(self.loaded(), key=lambda r: r["seq"])
        self.assertEqual([r["prompt"] for r in rows], ["first", "second with @sub/x.txt"])
        self.assertEqual(len(rows[0]["attachments"]), 0)
        self.assertEqual(len(rows[1]["attachments"]), 1)

    def test_malformed_input_never_raises(self):
        # missing keys / wrong types must not raise
        self.hook.on_user_prompt_submit({})
        self.hook.on_stop({})
        self.hook.on_user_prompt_submit({"prompt": None, "cwd": None})

    def test_entry_script_exit0_no_stdout(self):
        payload = {"session_id": "s9", "cwd": self.cwd, "prompt": "via subprocess",
                   "transcript_path": self.transcript, "hook_event_name": "UserPromptSubmit"}
        env = dict(os.environ, CLAUDE_HISTORY_SURFER_DIR=self.data_dir)
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO, "hooks", "log_prompt.py")],
            input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")        # must not inject into context
        rows = [r for r in self.store.load_all(include_deleted=True)
                if r["session_id"] == "s9"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt"], "via subprocess")


if __name__ == "__main__":
    unittest.main()
