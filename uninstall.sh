#!/usr/bin/env bash
# Uninstaller (leaves your captured prompt data intact):
#   curl -fsSL https://raw.githubusercontent.com/ContextLab/claude-history-surfer/main/uninstall.sh | bash
# Or from a clone:  ./uninstall.sh
set -euo pipefail

DEFAULT_HOME="$HOME/.claude/history-surfer-app"
SELF="${BASH_SOURCE[0]:-$0}"
APP_HOME=""
if [ -f "$SELF" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
  if [ -d "$SCRIPT_DIR/history_surfer" ]; then
    APP_HOME="$SCRIPT_DIR"
  fi
fi
[ -z "$APP_HOME" ] && APP_HOME="${CLAUDE_HISTORY_SURFER_APP:-$DEFAULT_HOME}"

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "error: python3 is required but not found on PATH." >&2
  exit 1
fi

exec "$PYTHON" "$APP_HOME/scripts/setup.py" --uninstall "$@"
