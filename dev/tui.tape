# dev/tui.tape — the hero demo: browse, inspect, live-filter, favorite
Output docs/media/tui.gif
Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 18
Set TypingSpeed 75ms
Type "surfer tui --all"  Enter  Sleep 2500ms
Down   Sleep 600ms
Down   Sleep 600ms
Down   Sleep 900ms
Enter  Sleep 2500ms      # detail view of the selected prompt
Enter  Sleep 1200ms      # back to the list
Type "/"       Sleep 700ms
Type "pytest"  Sleep 900ms
Enter  Sleep 1800ms      # live filter -> matching prompts only
Type "f"  Sleep 1500ms   # star it (favorite)
Enter  Sleep 2500ms      # detail shows FAVORITE
Enter  Sleep 900ms
Type "q"  Sleep 1200ms
