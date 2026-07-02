# Session notes — 2026-07-01 — export/replay build + full audit

Branch: feature/export-replay-readme (24+ commits from main; NOT yet merged/pushed)

## What was built
- `surfer export` — Markdown (default, lossless round-trip via len= guarded
  HTML-comment markers) + JSON. Reuses search/list scope+filters.
- `surfer replay <file>` — plays an export into a real Claude Code session via
  headless `claude -p` (`--session-id` → `--resume`, prompt after `--`).
  Selection: `--select "0,3-7,10-"` (order = execution order, duplicates re-run,
  out-of-range warns+skips, empty = clean no-op), `--first/--last`, `--dry-run`,
  `--model`, `--session-id`, `-o transcript.md`.
- README overhaul (🏄, motivation, GIFs in docs/media/, import-history default
  install); dev/ folder (seed_demo_store.py, vhs tapes, generate_media.sh);
  design doc + spec + plan in docs/superpowers/.

## Bug fixes landed same branch (user-reported)
- scope defaults → current project everywhere (skill, /history, stats)
- TUI colors (was white-on-white); pty test asserts SGR 46
- history depth surfaced (stats date spans, list --limit 0, skill guidance);
  store was NEVER shallow — holds everything Claude Code retains (~Sept 2025+)
- noise filtering: <task-notification>, [SYSTEM NOTIFICATION, <ide_opened_file>,
  <local-command-stdout>, [Request interrupted, <command-message>, <command-name>
  skipped at capture + hidden on read (include_noise=True recovers old ones)

## Audit (3 subagent auditors + controller pass) — all findings fixed
- Criticals: replay argv flag-injection (fixed with `--`, live-verified);
  <command-name> noise gap (fixed). Importants: replay aborts on claude failure
  (was silent), CRLF round-trip (newline="" both sides), README include_noise
  claim. Plus: export -o guard, --select ""≠all, reversed-range warning, scope
  hint, comma warning, stats --project label, README privacy leak (real project
  name in stats example) + contradiction, design.md --purge ghost flag.
- Accepted (not fixed, by design): no-len fallback can truncate HAND-EDITED .md
  embedding literal markers (surfer output always emits len=); tag text isn't
  validated against marker chars (extreme edge).

## State / how to resume
- Full suite: ./run_tests.sh → ALL TESTS PASSED. Live test:
  CLAUDE_HISTORY_SURFER_LIVE=1 PYTHONPATH=$PWD python3 tests/test_replay.py -v
- SDD ledger: .superpowers/sdd/progress.md (untracked scratch)
- Next: merge/PR decision is the only open item. Media regen: ./dev/generate_media.sh
