"""Real tests for install/uninstall — temp dirs, a real settings.json with
pre-existing keys, real symlinks. Never touches the user's real ~/.claude."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InstallerTest(unittest.TestCase):
    def setUp(self):
        from history_surfer import installer
        self.installer = installer
        self.tmp = tempfile.mkdtemp(prefix="hs-inst-")
        self.claude = Path(self.tmp) / ".claude"
        self.bin = Path(self.tmp) / "bin"
        self.claude.mkdir()
        # a realistic existing settings.json with unrelated keys + an unrelated hook
        self.settings_path = self.claude / "settings.json"
        self.existing = {
            "model": "opus",
            "permissions": {"allow": ["Bash(ls:*)"]},
            "env": {"FOO": "bar"},
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/other-tool"}]}
                ]
            },
        }
        self.settings_path.write_text(json.dumps(self.existing, indent=2))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- pure merge/remove ------------------------------------------------ #

    def test_merge_preserves_everything_and_adds_hooks(self):
        merged = self.installer.merge_hooks(self.existing, REPO, sys.executable)
        # unrelated keys untouched
        self.assertEqual(merged["model"], "opus")
        self.assertEqual(merged["env"], {"FOO": "bar"})
        self.assertEqual(merged["permissions"], {"allow": ["Bash(ls:*)"]})
        # unrelated hook preserved
        cmds = [h["command"] for g in merged["hooks"]["UserPromptSubmit"]
                for h in g["hooks"]]
        self.assertIn("/usr/bin/other-tool", cmds)
        self.assertTrue(any("hooks/log_prompt.py" in c for c in cmds))
        stop = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
        self.assertTrue(any("hooks/flush.py" in c for c in stop))

    def test_merge_idempotent(self):
        once = self.installer.merge_hooks(self.existing, REPO, sys.executable)
        twice = self.installer.merge_hooks(once, REPO, sys.executable)
        ours = [h["command"] for g in twice["hooks"]["UserPromptSubmit"]
                for h in g["hooks"] if "hooks/log_prompt.py" in h["command"]]
        self.assertEqual(len(ours), 1)

    def test_remove_hooks_restores_and_keeps_unrelated(self):
        merged = self.installer.merge_hooks(self.existing, REPO, sys.executable)
        removed = self.installer.remove_hooks(merged)
        cmds = [h["command"] for g in removed.get("hooks", {}).get("UserPromptSubmit", [])
                for h in g["hooks"]]
        self.assertIn("/usr/bin/other-tool", cmds)
        self.assertFalse(any("hooks/log_prompt.py" in c for c in cmds))
        self.assertNotIn("Stop", removed.get("hooks", {}))  # our-only event dropped
        self.assertEqual(removed["model"], "opus")

    def test_refuses_invalid_json(self):
        self.settings_path.write_text("{ not valid json")
        with self.assertRaises(SystemExit):
            self.installer.read_settings(self.settings_path)

    # -- full install / uninstall ---------------------------------------- #

    def test_install_full(self):
        rep = self.installer.install(REPO, self.claude, self.bin, sys.executable)

        surfer = self.bin / "surfer"
        self.assertTrue(surfer.is_symlink())
        self.assertEqual(os.readlink(surfer), str(Path(REPO) / "bin" / "surfer"))

        # backup created, existing keys preserved, our hooks present
        self.assertTrue(rep["settings_backup"])
        self.assertTrue(Path(rep["settings_backup"]).exists())
        new = json.loads(self.settings_path.read_text())
        self.assertEqual(new["model"], "opus")
        self.assertEqual(new["env"], {"FOO": "bar"})
        subs = [h["command"] for g in new["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        self.assertTrue(any("hooks/log_prompt.py" in c for c in subs))
        self.assertIn("/usr/bin/other-tool", subs)

        # skill + command symlinks
        self.assertTrue((self.claude / "skills" / "history-surfer").is_symlink())
        self.assertTrue((self.claude / "commands" / "history.md").is_symlink())

        # data dir scaffolded
        self.assertTrue((self.claude / "history-surfer" / "projects").is_dir())

    def test_install_idempotent(self):
        self.installer.install(REPO, self.claude, self.bin, sys.executable)
        self.installer.install(REPO, self.claude, self.bin, sys.executable)
        new = json.loads(self.settings_path.read_text())
        ours = [h["command"] for g in new["hooks"]["UserPromptSubmit"]
                for h in g["hooks"] if "hooks/log_prompt.py" in h["command"]]
        self.assertEqual(len(ours), 1)

    def test_uninstall(self):
        self.installer.install(REPO, self.claude, self.bin, sys.executable)
        self.installer.uninstall(REPO, self.claude, self.bin)
        # symlinks gone
        self.assertFalse((self.bin / "surfer").exists())
        self.assertFalse((self.claude / "skills" / "history-surfer").exists())
        self.assertFalse((self.claude / "commands" / "history.md").exists())
        # our hooks gone, unrelated hook + other keys preserved
        new = json.loads(self.settings_path.read_text())
        subs = [h["command"] for g in new.get("hooks", {}).get("UserPromptSubmit", [])
                for h in g["hooks"]]
        self.assertIn("/usr/bin/other-tool", subs)
        self.assertFalse(any("hooks/log_prompt.py" in c for c in subs))
        self.assertEqual(new["model"], "opus")
        # data dir left intact
        self.assertTrue((self.claude / "history-surfer" / "projects").is_dir())

    def test_end_to_end_setup_script(self):
        """Run scripts/setup.py as a real subprocess against temp dirs."""
        import subprocess
        env = dict(os.environ)
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "setup.py"),
             "--claude-dir", str(self.claude), "--bin-dir", str(self.bin)],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Installed claude-history-surfer", proc.stdout)
        self.assertTrue((self.bin / "surfer").is_symlink())


if __name__ == "__main__":
    unittest.main()
