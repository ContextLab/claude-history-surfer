"""Replay exported prompts into a Claude Code session via the `claude` CLI.

parse_selection turns a spec like "0,3-7,10-" into an ordered index list
(duplicates kept; out-of-range warns and is skipped). run_replay drives the
installed `claude` CLI headless, keeping one session across prompts.
"""

import subprocess
import uuid


def parse_selection(spec, count):
    """(indices_in_execution_order, warnings). See module docstring for grammar."""
    indices, warnings = [], []
    s = (spec or "").strip()
    if s.startswith("["):
        s = s[1:]
    if s.endswith("]"):
        s = s[:-1]
    for raw in s.split(","):
        tok = raw.strip()
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            try:
                start = int(a) if a.strip() else 0
                end = int(b) if b.strip() else count - 1
            except ValueError:
                warnings.append("invalid selection token %r" % tok)
                continue
            if start >= count:
                warnings.append(
                    "selection %r starts past last index %d" % (tok, count - 1))
                continue
            if end > count - 1:
                warnings.append(
                    "selection %r truncated at last index %d" % (tok, count - 1))
                end = count - 1
            for i in range(max(start, 0), end + 1):
                indices.append(i)
        else:
            try:
                i = int(tok)
            except ValueError:
                warnings.append("invalid selection token %r" % tok)
                continue
            if 0 <= i < count:
                indices.append(i)
            else:
                warnings.append("index %d out of range (0..%d)" % (i, count - 1))
    return indices, warnings


def select_indices(count, select=None, first=None, last=None):
    if first is not None:
        return list(range(0, min(first, count))), []
    if last is not None:
        return list(range(max(0, count - last), count)), []
    if select:
        return parse_selection(select, count)
    return list(range(count)), []


def build_claude_argv(prompt_text, session_id, is_first, model=None):
    argv = ["claude", "-p", prompt_text]
    argv += (["--session-id", session_id] if is_first
             else ["--resume", session_id])
    if model:
        argv += ["--model", model]
    return argv
