#!/usr/bin/env bash
# One-line installer:
#   curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/install.sh | bash
# Or from a clone:  ./install.sh   (add --import-history to seed past prompts)
set -euo pipefail

REPO_URL="https://github.com/ContextLab/claude-history-surfer.git"
DEFAULT_HOME="$HOME/.claude/history-surfer-app"

# Are we running from inside a clone (script sits next to history_surfer/)?
SELF="${BASH_SOURCE[0]:-$0}"
APP_HOME=""
if [ -f "$SELF" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
  if [ -d "$SCRIPT_DIR/history_surfer" ]; then
    APP_HOME="$SCRIPT_DIR"
  fi
fi

if [ -z "$APP_HOME" ]; then
  APP_HOME="${CLAUDE_HISTORY_SURFER_APP:-$DEFAULT_HOME}"
  if [ -d "$APP_HOME/.git" ]; then
    echo "Updating existing install at $APP_HOME ..."
    git -C "$APP_HOME" pull --ff-only
  else
    echo "Cloning claude-history-surfer into $APP_HOME ..."
    git clone --depth 1 "$REPO_URL" "$APP_HOME"
  fi
fi

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "error: python3 is required but not found on PATH." >&2
  exit 1
fi

exec "$PYTHON" "$APP_HOME/scripts/setup.py" "$@"
