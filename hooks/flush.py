#!/usr/bin/env python3
"""Stop hook entry point.

Runs after each turn completes, when the transcript is fully flushed, to
reconcile pasted images and canonical full text for the turn's prompt(s).
Contract: never write to stdout; always exit 0.
"""

import json
import os
import sys


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    try:
        from history_surfer import hook
        hook.on_stop(data)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
