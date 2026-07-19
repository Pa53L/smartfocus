"""macOS Do Not Disturb / Focus mode toggle.

Tries multiple strategies to enable/disable DND on macOS:
1. AppleScript via Control Center (requires accessibility permissions)
2. Fallback: returns False so caller can nudge the user

Idempotent: checks current DND state before toggling to avoid
toggling in the wrong direction.
"""

from __future__ import annotations

import subprocess
import sys
import pathlib


def _is_dnd_active() -> bool:
    """Best-effort check if DND/Focus is currently active on macOS."""
    try:
        p = pathlib.Path.home() / "Library" / "DoNotDisturb" / "DB" / "Assertions.json"
        if not p.exists():
            return False
        content = p.read_text(encoding="utf-8").strip()
        # Non-empty assertions file with data entries means DND is active
        return len(content) > 20 and '"data"' in content
    except Exception:
        return False


def _try_control_center() -> bool:
    """Toggle Focus via AppleScript Control Center automation."""
    if sys.platform != "darwin":
        return False

    script = """
    tell application "System Events"
        tell application process "ControlCenter"
            click menu bar item "Control Center" of menu bar 1
            delay 0.5
            try
                click button "Focus" of group 1 of window "Control Center"
                delay 0.3
                click button "Do Not Disturb" of group 1 of window "Control Center"
                delay 0.2
                click menu bar item "Control Center" of menu bar 1
                return "ok"
            on error errMsg
                try
                    click menu bar item "Control Center" of menu bar 1
                end try
                return "error:" & errMsg
            end try
        end tell
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and "ok" in (result.stdout or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _try_shortcuts() -> bool:
    """Try to toggle via Shortcuts CLI if a DND shortcut exists."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["shortcuts", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False
        output = (result.stdout or "").lower()
        for name in ["do not disturb", "не беспокоить", "focus"]:
            if name in output:
                subprocess.run(["shortcuts", "run", name.title()], timeout=10)
                return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return False


def _toggle_dnd() -> bool:
    """Toggle DND state once. Returns True if the toggle succeeded."""
    if _try_shortcuts():
        return True
    return _try_control_center()


def enable_dnd() -> bool:
    """Enable Do Not Disturb on macOS. Idempotent — skips if already active."""
    if sys.platform != "darwin":
        return False
    if _is_dnd_active():
        return True
    return _toggle_dnd()


def disable_dnd() -> bool:
    """Disable Do Not Disturb on macOS. Idempotent — skips if already inactive."""
    if sys.platform != "darwin":
        return False
    if not _is_dnd_active():
        return True
    return _toggle_dnd()
