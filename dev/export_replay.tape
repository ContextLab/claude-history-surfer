# dev/export_replay.tape
Output docs/media/export-replay.gif
Set FontSize 18
Set Width 1100
Set Height 700
Set Padding 18
Type "surfer export --all --favorites -o faves.md"   Enter   Sleep 1500ms
Type "head -20 faves.md"   Enter   Sleep 2500ms
Type "surfer replay faves.md --dry-run"   Enter   Sleep 2500ms
Sleep 1s
