# Developing claude-history-surfer

Developer notes and tooling. **None of this is needed to *use* the tool** — the
user installer never touches anything here.

## Layout
- `history_surfer/` — the package (pure Python stdlib; no pip deps).
- `tests/` — real tests (`unittest`; no mocks). Run `./run_tests.sh`.
- `docs/design.md` — architecture. `docs/superpowers/` — specs & plans.
- `dev/` — this folder: media generation + demo data.

## Running tests
```bash
./run_tests.sh                     # full suite
PYTHONPATH=$PWD python3 tests/test_replay.py -v   # one file
CLAUDE_HISTORY_SURFER_LIVE=1 ./run_tests.sh        # include the live replay call
```

## Generating the README media (screenshots + GIF)
Media is recorded against a **fabricated demo store** (`dev/seed_demo_store.py`)
so no real prompts, paths, or secrets are captured.

Dev-only dependency: [`vhs`](https://github.com/charmbracelet/vhs).
```bash
brew install vhs        # macOS; see vhs docs for Linux
./dev/generate_media.sh # seeds a temp store, records tapes → docs/media/
```
Tapes: `dev/cli.tape`, `dev/tui.tape`, `dev/export_replay.tape`.

## Architecture notes
Hybrid capture (UserPromptSubmit + Stop hooks), an append-only capture layer, and
a separate append-only curation overlay merged on read — see `docs/design.md`.
Export/replay are read-only over the store and share one normalized record shape
(`history_surfer/exporter.py`); replay drives the `claude` CLI headless
(`history_surfer/replay.py`). Full design:
`docs/superpowers/specs/2026-07-01-export-replay-readme-design.md`.
