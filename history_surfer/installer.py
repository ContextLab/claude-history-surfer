"""Install / uninstall logic (importable + testable).

The risky part is editing ~/.claude/settings.json (31 KB of real config). The
merge is a pure function that only touches the ``hooks`` key, preserving every
other key, and the file is backed up before any write. Everything takes explicit
paths so tests can run entirely against temp directories.
"""

import json
import os
import shutil
import time
from pathlib import Path

SUBMIT_MARKER = "hooks/log_prompt.py"
STOP_MARKER = "hooks/flush.py"


# --------------------------------------------------------------------------- #
# pure hook-merge logic
# --------------------------------------------------------------------------- #

def _cmd(python, script):
    return '"%s" "%s"' % (python, script)


def _upsert(arr, marker, cmd):
    """Return a new hook-group list with our command inserted or updated."""
    arr = [dict(g) for g in (arr or [])]
    for g in arr:
        hooks = g.get("hooks") or []
        for h in hooks:
            if marker in (h.get("command") or ""):
                h["command"] = cmd  # update in place (e.g. python path changed)
                return arr
    arr.append({"hooks": [{"type": "command", "command": cmd}]})
    return arr


def merge_hooks(settings, app_home, python):
    settings = dict(settings)
    hooks = dict(settings.get("hooks") or {})
    submit = _cmd(python, str(Path(app_home) / "hooks" / "log_prompt.py"))
    stop = _cmd(python, str(Path(app_home) / "hooks" / "flush.py"))
    hooks["UserPromptSubmit"] = _upsert(hooks.get("UserPromptSubmit"), SUBMIT_MARKER, submit)
    hooks["Stop"] = _upsert(hooks.get("Stop"), STOP_MARKER, stop)
    settings["hooks"] = hooks
    return settings


def remove_hooks(settings):
    settings = dict(settings)
    hooks = dict(settings.get("hooks") or {})
    for event, marker in (("UserPromptSubmit", SUBMIT_MARKER), ("Stop", STOP_MARKER)):
        arr = []
        for g in (hooks.get(event) or []):
            kept = [h for h in (g.get("hooks") or []) if marker not in (h.get("command") or "")]
            if kept:
                g = dict(g)
                g["hooks"] = kept
                arr.append(g)
            elif not (g.get("hooks")):
                arr.append(g)  # preserve unrelated empty groups untouched
        if arr:
            hooks[event] = arr
        else:
            hooks.pop(event, None)
    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)
    return settings


# --------------------------------------------------------------------------- #
# settings file IO (with backup)
# --------------------------------------------------------------------------- #

def read_settings(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise SystemExit("Refusing to edit %s: it is not valid JSON." % path)


def backup_settings(path):
    path = Path(path)
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(path.name + ".bak-" + stamp)
    shutil.copy2(path, bak)
    return bak


def write_settings(path, settings):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# symlinks
# --------------------------------------------------------------------------- #

def _symlink_force(src, dst):
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        if dst.is_symlink() and os.readlink(dst) == str(src):
            return "unchanged"
        if dst.is_dir() and not dst.is_symlink():
            raise SystemExit("Refusing to replace real directory %s" % dst)
        dst.unlink()
    dst.symlink_to(src)
    return "linked"


def _unlink_if_ours(dst, expected_src):
    dst = Path(dst)
    if dst.is_symlink() and os.readlink(dst) == str(expected_src):
        dst.unlink()
        return True
    return False


# --------------------------------------------------------------------------- #
# install / uninstall
# --------------------------------------------------------------------------- #

def install(app_home, claude_dir, bin_dir, python, data_dir=None):
    app_home = Path(app_home)
    claude_dir = Path(claude_dir)
    bin_dir = Path(bin_dir)
    report = {}

    # 1. CLI on PATH
    report["surfer"] = _symlink_force(app_home / "bin" / "surfer", bin_dir / "surfer")

    # 2. settings.json hooks (backup + merge)
    settings_path = claude_dir / "settings.json"
    report["settings_backup"] = str(backup_settings(settings_path) or "")
    merged = merge_hooks(read_settings(settings_path), str(app_home), python)
    write_settings(settings_path, merged)
    report["hooks"] = "merged"

    # 3. skill + slash command
    report["skill"] = _symlink_force(app_home / "skills" / "history-surfer",
                                     claude_dir / "skills" / "history-surfer")
    report["command"] = _symlink_force(app_home / "commands" / "history.md",
                                       claude_dir / "commands" / "history.md")

    # 4. data dir — resolve the same way config.data_dir() does, so the dir the
    #    installer scaffolds is exactly the one the hook/CLI/import will use.
    if data_dir:
        dd = Path(data_dir)
    elif os.environ.get("CLAUDE_HISTORY_SURFER_DIR"):
        dd = Path(os.environ["CLAUDE_HISTORY_SURFER_DIR"]).expanduser()
    else:
        dd = claude_dir / "history-surfer"
    (dd / "projects").mkdir(parents=True, exist_ok=True)
    (dd / "state").mkdir(parents=True, exist_ok=True)
    (dd / "meta").mkdir(parents=True, exist_ok=True)
    report["data_dir"] = str(dd)

    return report


def uninstall(app_home, claude_dir, bin_dir):
    app_home = Path(app_home)
    claude_dir = Path(claude_dir)
    bin_dir = Path(bin_dir)
    report = {}

    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        report["settings_backup"] = str(backup_settings(settings_path) or "")
        write_settings(settings_path, remove_hooks(read_settings(settings_path)))
        report["hooks"] = "removed"

    report["surfer"] = _unlink_if_ours(bin_dir / "surfer", app_home / "bin" / "surfer")
    report["skill"] = _unlink_if_ours(claude_dir / "skills" / "history-surfer",
                                      app_home / "skills" / "history-surfer")
    report["command"] = _unlink_if_ours(claude_dir / "commands" / "history.md",
                                        app_home / "commands" / "history.md")
    report["data_note"] = "prompt data left intact under ~/.claude/history-surfer"
    return report
