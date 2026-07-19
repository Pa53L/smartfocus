"""Notification queue and filtering logic for SmartFocus."""

from __future__ import annotations

from datetime import datetime
from models import Notification, NotificationAction, FocusSession
import state


def evaluate_notification(notif: Notification, session_active: bool,
                          session_id: str = "") -> Notification:
    if not session_active:
        notif.action = NotificationAction.SHOW_NOW
        notif.action_explanation = "No active focus session — showing immediately."
        return notif
    reasons = []
    if notif.requires_action and notif.is_important:
        notif.action = NotificationAction.SHOW_NOW
        reasons.append("requires action and is important")
    elif notif.related_to_current_task and notif.has_deadline:
        notif.action = NotificationAction.SHOW_NOW
        reasons.append("related to current task and has a deadline")
    elif notif.has_deadline:
        notif.action = NotificationAction.SHOW_NOW
        reasons.append("has a deadline — showing regardless")
    else:
        notif.action = NotificationAction.DEFER
        reasons.append("not urgent — deferring until session ends")
    notif.action_explanation = "; ".join(reasons) + (f" (session: {session_id[:8]})" if session_id else "")
    state.log_action("notification_decision",
                      f"{notif.title}: {notif.action.value} — {notif.action_explanation}")
    return notif


def process_notification_batch(notifications: list[Notification],
                                session_active: bool,
                                session_id: str = "") -> list[Notification]:
    return [evaluate_notification(n, session_active, session_id) for n in notifications]


def get_urgent_notifications(notifications: list[Notification]) -> list[Notification]:
    return [n for n in notifications if n.action == NotificationAction.SHOW_NOW]


def get_deferred_notifications(notifications: list[Notification]) -> list[Notification]:
    return [n for n in notifications if n.action == NotificationAction.DEFER]


def create_synthetic_notification(data: dict) -> Notification:
    return Notification(
        source=data.get("source", ""),
        title=data.get("title", ""),
        body=data.get("body", ""),
        timestamp=datetime.now(),
        requires_action=data.get("requires_action", False),
        has_deadline=data.get("has_deadline", False),
        is_important=data.get("is_important", False),
        related_to_current_task=data.get("related_to_task", False),
    )


def evaluate_notification_priority(notif: Notification,
                                    current_task_priority: float,
                                    session_active: bool) -> Notification:
    """Evaluate notification against current task priority.

    Only show notification if its effective priority is HIGHER than the
    current task's priority score. Otherwise defer silently.
    """
    if not session_active:
        notif.action = NotificationAction.SHOW_NOW
        notif.action_explanation = "No active session — showing immediately."
        return notif

    # Compute notification's effective priority (0-1 scale)
    notif_priority = 0.3  # base
    if notif.is_important:
        notif_priority += 0.3
    if notif.requires_action:
        notif_priority += 0.2
    if notif.has_deadline:
        notif_priority += 0.2

    if notif_priority > current_task_priority:
        notif.action = NotificationAction.SHOW_NOW
        notif.action_explanation = (
            f"Priority {notif_priority:.2f} > current task {current_task_priority:.2f} — showing."
        )
    else:
        notif.action = NotificationAction.DEFER
        notif.action_explanation = (
            f"Priority {notif_priority:.2f} <= current task {current_task_priority:.2f} — deferred."
        )

    state.log_action("notification_priority_check",
                      f"{notif.title}: {notif.action.value} — {notif.action_explanation}")
    return notif


def generate_session_notification_summary(session_id: str) -> dict:
    """Generate a summary of all notifications received during a session.

    Returns counts of shown vs deferred, plus any emails received.
    """
    emails = state.get_session_emails(session_id)
    task_emails = [e for e in emails if e.get("has_task")]
    non_task_emails = [e for e in emails if not e.get("has_task")]

    # Get session data for any logged notification decisions
    sessions = state.get_sessions()
    session_data = None
    for s in sessions:
        if s.get("id") == session_id:
            session_data = s
            break

    focus_checks = []
    if session_data:
        focus_checks = session_data.get("focus_checks", [])

    return {
        "total_emails": len(emails),
        "task_emails": len(task_emails),
        "non_task_emails": len(non_task_emails),
        "task_email_details": task_emails[:20],
        "non_task_email_subjects": [e.get("subject", "") for e in non_task_emails[:20]],
        "focus_checks_count": len(focus_checks),
        "focus_check_scores": [c.get("score", 0) for c in focus_checks],
        "deferred_count": len(non_task_emails),  # emails deferred during session
        "summary": (
            f"During this session: {len(emails)} emails received "
            f"({len(task_emails)} task-tagged, {len(non_task_emails)} other). "
            f"Focus checked {len(focus_checks)} times."
        ),
    }
