"""Configuration and path resolution.

All paths derive from the data directory, which is (in priority order):
  1. $CLAUDE_HISTORY_SURFER_DIR
  2. ~/.claude/history-surfer
"""

import os
from pathlib import Path

APP_NAME = "claude-history-surfer"

# Attachments larger than this are skipped (with a note) rather than copied.
MAX_ATTACHMENT_BYTES = int(
    os.environ.get("CLAUDE_HISTORY_SURFER_MAX_ATTACH", str(25 * 1024 * 1024))
)

# Prompt text longer than this (chars) is also stored as a `text` attachment
# blob and truncated to a preview inline, so prompts.jsonl stays scannable.
LARGE_TEXT_THRESHOLD = int(
    os.environ.get("CLAUDE_HISTORY_SURFER_LARGE_TEXT", str(50_000))
)


def home() -> Path:
    return Path.home()


def claude_dir() -> Path:
    """Claude Code's own data directory (~/.claude)."""
    override = os.environ.get("CLAUDE_HISTORY_SURFER_CLAUDE_DIR")
    if override:
        return Path(override).expanduser()
    return home() / ".claude"


def data_dir() -> Path:
    """Where this tool stores captured prompts + attachments."""
    override = os.environ.get("CLAUDE_HISTORY_SURFER_DIR")
    if override:
        return Path(override).expanduser()
    return claude_dir() / "history-surfer"


def projects_dir() -> Path:
    return data_dir() / "projects"


def state_dir() -> Path:
    return data_dir() / "state"


def meta_dir() -> Path:
    return data_dir() / "meta"


def errors_log() -> Path:
    return meta_dir() / "errors.log"


def history_jsonl() -> Path:
    """Claude Code's global prompt history file."""
    return claude_dir() / "history.jsonl"
