#!/usr/bin/env bash
# Run the full test suite (stdlib unittest; real tests, no mocks).
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
fail=0
for t in tests/test_*.py; do
  echo "=== $t ==="
  if ! python3 "$t" -v; then
    fail=1
  fi
done
if [ "$fail" -ne 0 ]; then
  echo "SOME TESTS FAILED"
  exit 1
fi
echo "ALL TESTS PASSED"
