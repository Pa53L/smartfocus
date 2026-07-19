"""Thunderbird mbox scanner — incremental email scanning for task extraction.

Scans the Thunderbird INBOX mbox file incrementally (byte-offset tracking)
to find new emails. Extracts [task-XXX] patterns from subjects and returns
structured results. Handles Cyrillic (RFC 2047) encoded headers.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Optional

# Allow importing sibling skill modules
_SKILL_DIR = pathlib.Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

import state

TASK_PATTERN = re.compile(r"\[task[-_]?(\w+)\]", re.IGNORECASE)
TAIL_BUFFER_BYTES = 2 * 1024 * 1024  # 2 MB tail for initial scan
MAX_MESSAGES_PER_SCAN = 200
MAX_SEEN_IDS = 10000


# ─── Profile detection ────────────────────────────────


def find_thunderbird_profile() -> Optional[str]:
    """Auto-detect the active Thunderbird profile path."""
    env_path = os.environ.get("THUNDERBIRD_PROFILE", "")
    if env_path and pathlib.Path(env_path).exists():
        return env_path

    ini_path = None
    for candidate in [
        pathlib.Path(os.path.expanduser("~/Library/Thunderbird/profiles.ini")),
        pathlib.Path(os.path.expanduser("~/.thunderbird/profiles.ini")),
    ]:
        if candidate.exists():
            ini_path = candidate
            break
    if not ini_path:
        return None

    profiles: list[dict] = []
    current: dict = {}
    for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            if current:
                profiles.append(current)
            current = {"section": line[1:-1]}
        elif "=" in line:
            key, val = line.split("=", 1)
            current[key.strip()] = val.strip()
    if current:
        profiles.append(current)

    tb_root = ini_path.parent

    # First: find the Install section — it has Default=<path> and Locked=1
    for p in profiles:
        section = p.get("section", "")
        if section.startswith("Install") and p.get("Locked") == "1":
            default_path = p.get("Default", "")
            if default_path:
                full = tb_root / default_path
                if full.exists():
                    return str(full)

    # Next: prefer profile with Default=1
    for p in profiles:
        if p.get("Default") == "1":
            full = _resolve_profile_path(tb_root, p)
            if full:
                return str(full)

    # Last resort: first profile
    for p in profiles:
        if p.get("Path"):
            full = _resolve_profile_path(tb_root, p)
            if full:
                return str(full)
    return None


def _resolve_profile_path(tb_root: pathlib.Path, profile: dict) -> Optional[pathlib.Path]:
    path = profile.get("Path", "")
    if not path:
        return None
    if profile.get("IsRelative") == "1":
        full = tb_root / path
    else:
        full = pathlib.Path(path)
    return full if full.exists() else None


def get_inbox_path(profile_path: str) -> Optional[str]:
    """Find the INBOX mbox file in the Thunderbird profile."""
    imap_dir = pathlib.Path(profile_path) / "ImapMail"
    if not imap_dir.exists():
        return None
    for server_dir in sorted(imap_dir.iterdir()):
        if not server_dir.is_dir():
            continue
        inbox = server_dir / "INBOX"
        if inbox.exists() and inbox.stat().st_size > 0:
            return str(inbox)
    return None


# ─── Header parsing ───────────────────────────────────


def _decode_header_value(value: str) -> str:
    """Decode RFC 2047 encoded header (handles Cyrillic)."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_message_info(raw_bytes: bytes) -> Optional[dict]:
    """Parse raw mbox message bytes and extract relevant info."""
    # Skip the "From " separator line
    if raw_bytes.startswith(b"From "):
        nl = raw_bytes.find(b"\n")
        if nl > 0:
            raw_bytes = raw_bytes[nl + 1:]

    try:
        msg = message_from_bytes(raw_bytes)
    except Exception:
        return None

    subject = _decode_header_value(msg.get("Subject", ""))
    from_ = _decode_header_value(msg.get("From", ""))
    message_id = msg.get("Message-ID", "")
    date_str = msg.get("Date", "")

    try:
        date = parsedate_to_datetime(date_str) if date_str else datetime.now()
        # Convert timezone-aware datetimes to naive local time so they are
        # compatible with datetime.now() in prioritize.py and elsewhere.
        if isinstance(date, datetime) and date.tzinfo is not None:
            date = date.astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        date = datetime.now()

    task_match = TASK_PATTERN.search(subject)
    task_id = task_match.group(1) if task_match else None

    return {
        "message_id": message_id,
        "subject": subject,
        "from": from_,
        "date": date.isoformat() if isinstance(date, datetime) else str(date),
        "task_id": task_id,
        "has_task": task_id is not None,
    }


# ─── Incremental scanning ─────────────────────────────


def scan_inbox_incremental(inbox_path: str, last_offset: int = 0,
                           seen_ids: set | None = None) -> tuple[list[dict], int]:
    """Scan INBOX mbox for new messages since last_offset.

    Returns (new_messages, new_offset).
    """
    seen_ids = seen_ids or set()
    file_size = os.path.getsize(inbox_path)

    # If file shrank (compaction), reset to tail
    if file_size < last_offset:
        last_offset = max(0, file_size - TAIL_BUFFER_BYTES)

    # No new data
    if last_offset > 0 and file_size <= last_offset:
        return [], file_size

    # Read new (or tail) data
    with open(inbox_path, "rb") as f:
        if last_offset == 0:
            read_start = max(0, file_size - TAIL_BUFFER_BYTES)
            f.seek(read_start)
        else:
            f.seek(last_offset)
        data = f.read()

    new_offset = file_size

    # Split into messages by "From " lines at start of line
    messages: list[dict] = []
    raw_messages: list[bytes] = []
    current_lines: list[bytes] = []
    in_message = False

    for line in data.split(b"\n"):
        if line.startswith(b"From ") and in_message and current_lines:
            raw_messages.append(b"\n".join(current_lines))
            current_lines = [line]
        elif line.startswith(b"From ") and not in_message:
            in_message = True
            current_lines = [line]
        elif in_message:
            current_lines.append(line)

    if current_lines:
        raw_messages.append(b"\n".join(current_lines))

    for raw in raw_messages:
        info = _extract_message_info(raw)
        if not info:
            continue
        mid = info.get("message_id", "")
        if mid and mid in seen_ids:
            continue
        if mid:
            seen_ids.add(mid)
        messages.append(info)

    # Cap results
    if len(messages) > MAX_MESSAGES_PER_SCAN:
        messages = messages[-MAX_MESSAGES_PER_SCAN:]

    return messages, new_offset


# ─── Full scan cycle ──────────────────────────────────


def scan_emails(profile_path: str | None = None, state_dir: str | None = None) -> dict:
    """Full scan cycle: load state, scan inbox, save state, return results.

    Returns:
        {
            "new_emails": [...],
            "new_task_emails": [...],
            "total_seen": int,
            "error": str | None
        }
    """
    if not profile_path:
        profile_path = find_thunderbird_profile()
    if not profile_path:
        return {"new_emails": [], "new_task_emails": [], "total_seen": 0,
                "error": "Thunderbird profile not found"}

    inbox_path = get_inbox_path(profile_path)
    if not inbox_path:
        return {"new_emails": [], "new_task_emails": [], "total_seen": 0,
                "error": "INBOX not found in profile"}

    # Load email state from SQLite
    email_state = state.get_email_state()
    seen_ids = set(email_state.get("seen_ids", []))
    last_offset = email_state.get("offset", 0)

    new_messages, new_offset = scan_inbox_incremental(inbox_path, last_offset, seen_ids)

    # Save state to SQLite
    email_state["seen_ids"] = list(seen_ids)[-MAX_SEEN_IDS:]
    email_state["offset"] = new_offset
    email_state["last_scan"] = datetime.now().isoformat()
    state.save_email_state(email_state)

    task_emails = [m for m in new_messages if m.get("has_task")]

    return {
        "new_emails": new_messages,
        "new_task_emails": task_emails,
        "total_seen": len(seen_ids),
        "error": None,
    }


# ─── Task creation from emails ─────────────────────────


def create_tasks_from_emails(task_emails: list[dict]) -> int:
    """Create Task objects from emails with [task-XXX] tags.

    Deduplicates by source_ref (the task tag). Returns count of new tasks created.
    Imported tasks get source=EMAIL and default importance/urgency/complexity (3/3/3),
    so they enter the common task list and are evaluated by the Eisenhower matrix
    alongside manual and synthetic tasks.
    """
    import models

    existing_tasks = state.get_tasks()
    existing_refs = {t.get("source_ref", "") for t in existing_tasks if t.get("source_ref")}

    new_count = 0
    for email in task_emails:
        raw_tag = email.get("task_id", "")
        if not raw_tag:
            continue
        source_ref = f"[task-{raw_tag}]"
        if source_ref in existing_refs:
            continue

        subject = email.get("subject", "")
        t = models.Task(
            title=subject,
            source=models.TaskSource.EMAIL,
            source_ref=source_ref,
        )
        t.compute_quadrant()
        state.append_task(t.to_dict())
        existing_refs.add(source_ref)
        new_count += 1

    return new_count
