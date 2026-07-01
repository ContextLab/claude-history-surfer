#!/usr/bin/env python3
"""Install/uninstall driver. Called by install.sh / uninstall.sh (or directly).

Wires up the CLI, hooks, skill, and slash command; leaves prompt data intact on
uninstall. All heavy lifting is in history_surfer.installer (which is tested)."""

import argparse
import os
import sys
from pathlib import Path

APP_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_HOME not in sys.path:
    sys.path.insert(0, APP_HOME)

from history_surfer import installer  # noqa: E402


def main():
    ap = argparse.ArgumentParser(prog="claude-history-surfer setup")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--import-history", action="store_true",
                    help="seed from ~/.claude/history.jsonl after install")
    ap.add_argument("--claude-dir", default=str(Path.home() / ".claude"))
    ap.add_argument("--bin-dir", default=str(Path.home() / ".local" / "bin"))
    args = ap.parse_args()
    python = sys.executable or "python3"

    if args.uninstall:
        rep = installer.uninstall(APP_HOME, args.claude_dir, args.bin_dir)
        print("Uninstalled claude-history-surfer:")
        for k, v in rep.items():
            print("  %-16s %s" % (k, v))
        print("\nTo also delete your captured prompts: rm -rf ~/.claude/history-surfer")
        return 0

    rep = installer.install(APP_HOME, args.claude_dir, args.bin_dir, python)
    print("Installed claude-history-surfer:")
    for k, v in rep.items():
        print("  %-16s %s" % (k, v))

    if args.import_history:
        from history_surfer import importer
        n = importer.import_history(verbose=False)
        print("  imported         %d prompt(s) from history.jsonl" % n)

    bin_dir = args.bin_dir
    print("\nNext steps:")
    print("  1. Ensure %s is on your PATH." % bin_dir)
    print("  2. RESTART Claude Code (hooks load at startup) so capture begins.")
    print("  3. Try:  surfer list --all   |   surfer tui   |   /history <query>")
    if not args.import_history:
        print("  (Seed past prompts anytime with:  surfer import-history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
