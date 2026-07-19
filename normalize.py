"""Normalization: deduplication, linking, and standardization of incoming events."""

from __future__ import annotations

import re
from models import Task, TaskSource
import state

TASK_REF_PATTERN = re.compile(r"\[task[_\s]*(\d+)\]", re.IGNORECASE)


def extract_task_ref(text: str) -> str | None:
    if not text:
        return None
    m = TASK_REF_PATTERN.search(text)
    if m:
        return f"[task_{m.group(1)}]"
    return None


def normalize_email(raw: dict) -> dict:
    subject = (raw.get("subject") or "").strip()
    body = (raw.get("body") or "").strip()[:5000]
    ref = extract_task_ref(subject) or extract_task_ref(body)
    raw["subject"] = subject
    raw["body"] = body
    raw["task_ref_pattern"] = ref or ""
    raw["has_task_ref"] = ref is not None
    return raw


def normalize_message(raw: dict) -> dict:
    text = (raw.get("text") or "").strip()[:2000]
    ref = extract_task_ref(text)
    raw["text"] = text
    raw["task_ref_pattern"] = ref or ""
    raw["has_task_ref"] = ref is not None
    return raw


def dedup_emails(emails: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for e in emails:
        key = e.get("message_id") or e.get("subject", "") + str(e.get("received_at", ""))
        if key not in seen:
            seen.add(key)
            result.append(e)
        else:
            state.log_action("dedup_email", f"Duplicate email skipped: {e.get('message_id', '')}")
    return result


def link_email_to_task(email: dict, tasks: list[Task]) -> str | None:
    if not email.get("has_task_ref") or not email.get("task_ref_pattern"):
        return None
    for t in tasks:
        if t.source_ref and t.source_ref == email["task_ref_pattern"]:
            email["linked_task_id"] = t.id
            return t.id
    return None


def link_message_to_task(msg: dict, tasks: list[Task]) -> str | None:
    if msg.get("has_task_ref") and msg.get("task_ref_pattern"):
        for t in tasks:
            if t.source_ref and t.source_ref == msg["task_ref_pattern"]:
                msg["linked_task_id"] = t.id
                return t.id
    msg_lower = (msg.get("text") or "").lower()
    for t in tasks:
        if t.title and t.title.lower() in msg_lower:
            msg["linked_task_id"] = t.id
            return t.id
    return None


def normalize_all(raw_data: dict) -> dict:
    emails = [normalize_email(e) for e in raw_data.get("emails", [])]
    messages = [normalize_message(m) for m in raw_data.get("messages", [])]
    emails = dedup_emails(emails)
    task_dicts = raw_data.get("tasks", [])
    tasks = [Task.from_dict(t) if isinstance(t, dict) else t for t in task_dicts]
    for e in emails:
        link_email_to_task(e, tasks)
    for m in messages:
        link_message_to_task(m, tasks)
    raw_data["emails"] = emails
    raw_data["messages"] = messages
    state.log_action("normalize",
                     f"Processed {len(emails)} emails, {len(messages)} messages, {len(tasks)} tasks")
    return raw_data
