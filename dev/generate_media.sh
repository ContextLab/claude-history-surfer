#!/usr/bin/env bash
# Record README media from a fabricated demo store. Requires `vhs`.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v vhs >/dev/null || { echo "install vhs first: brew install vhs"; exit 1; }

DEMO="$(mktemp -d)"
trap 'rm -rf "$DEMO"' EXIT
python3 dev/seed_demo_store.py "$DEMO"

export CLAUDE_HISTORY_SURFER_DIR="$DEMO"
export PATH="$PWD/bin:$PATH"          # use the repo's surfer without installing
mkdir -p docs/media
for tape in cli tui export_replay; do
  echo "recording $tape..."
  ( cd "$DEMO" && CLAUDE_HISTORY_SURFER_DIR="$DEMO" vhs "$OLDPWD/dev/$tape.tape" )
done
# Each tape's `Output docs/media/...gif` is relative to the cwd vhs ran in
# ($DEMO, above), not the repo root — copy the recordings out before the
# trap below deletes $DEMO.
cp "$DEMO"/docs/media/*.gif docs/media/
echo "wrote docs/media/*.gif"
