#!/usr/bin/env python3
"""UserPromptSubmit hook entry point.

Reads the hook JSON on stdin, records the prompt, and enriches attachments.
Contract: NEVER write to stdout (it would be injected into the model context)
and ALWAYS exit 0 (a non-zero exit could block the user's prompt).
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
        hook.on_user_prompt_submit(data)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
