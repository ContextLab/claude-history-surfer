# dev/seed_demo_store.py
"""Seed a throwaway store with fabricated prompts for screenshots/recordings.

Usage: CLAUDE_HISTORY_SURFER_DIR=<dir> python3 dev/seed_demo_store.py
Nothing here is real user data — safe to record and commit the resulting media.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from history_surfer import store  # noqa: E402

DEMO = [
    ("/Users/surfer/projects/aurora", "sess1a2b3c4d", 1,
     "Scaffold a FastAPI service with a /health endpoint and a Dockerfile.",
     "2026-06-20T14:00:00Z", ["setup"], True),
    ("/Users/surfer/projects/aurora", "sess1a2b3c4d", 2,
     "Add a vector field overlay to the plot and animate it over time.",
     "2026-06-20T14:12:00Z", ["graphics"], True),
    ("/Users/surfer/projects/aurora", "sess1a2b3c4d", 3,
     "Write a pytest that renders the animation to a PNG and checks the frame count.",
     "2026-06-20T14:30:00Z", ["testing"], False),
    ("/Users/surfer/projects/tide", "sess9f8e7d6c", 1,
     "Refactor the auth middleware to use a hard session timeout of 30 minutes.",
     "2026-06-21T09:00:00Z", ["security"], False),
    ("/Users/surfer/projects/tide", "sess9f8e7d6c", 2,
     "/model", "2026-06-21T09:05:00Z", [], False),
]


def main(dest):
    os.environ["CLAUDE_HISTORY_SURFER_DIR"] = dest
    for cwd, sess, seq, prompt, ts, tags, fav in DEMO:
        slug = store.slugify_cwd(cwd)
        store.append_prompt({"ts": ts, "session_id": sess, "cwd": cwd,
                             "project_slug": slug, "seq": seq, "prompt": prompt,
                             "is_command": prompt.startswith("/"), "text_final": True})
        for t in tags:
            store.add_overlay_event(slug, sess, seq, "tag", t)
        if fav:
            store.add_overlay_event(slug, sess, seq, "favorite", True)
    print("Seeded demo store at %s" % dest)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         os.environ.get("CLAUDE_HISTORY_SURFER_DIR", "./dev/.demo-store"))
