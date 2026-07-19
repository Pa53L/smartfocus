"""Synthetic event generator for demo mode — three scenario datasets."""

from __future__ import annotations

from datetime import datetime, timedelta
from models import Task, TaskSource
import state


def _now():
    return datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)


def _task(title, source, deadline_days, importance, urgency, complexity,
          day_goal="", source_ref=""):
    t = Task(
        title=title,
        source=TaskSource(source),
        deadline=_now() + timedelta(days=deadline_days) if deadline_days is not None else None,
        importance=importance,
        urgency=urgency,
        complexity=complexity,
        day_goal_link=day_goal,
        source_ref=source_ref,
    )
    t.compute_quadrant()
    return t.to_dict()


def _email(message_id, ref, subject, body, from_addr="boss@company.com", hours=0, minutes=0):
    return {
        "message_id": f"<msg_{message_id}@company.com>",
        "from_addr": from_addr,
        "subject": subject,
        "body": body,
        "received_at": (_now() + timedelta(hours=hours, minutes=minutes)).isoformat(),
        "has_task_ref": ref is not None,
        "task_ref_pattern": ref or "",
    }


def _message(channel, sender, text, hours=0, minutes=0, ref=None):
    return {
        "channel": channel,
        "sender": sender,
        "text": text,
        "timestamp": (_now() + timedelta(hours=hours, minutes=minutes)).isoformat(),
        "has_task_ref": ref is not None,
        "task_ref_pattern": ref or "",
    }


DATASETS = {}


def dataset_successful_day() -> dict:
    base = _now()
    tasks = [
        _task("Fix login redirect bug", "email", 1, 4, 5, 2, "Blocks user testing", "[task_2]"),
        _task("Refactor authentication module", "email", 2, 5, 4, 4,
              "Improve security for production release", "[task_1]"),
    ]
    emails = [
        _email(1, "[task_1]", "Refactor authentication module [task_1]",
               "Please refactor the auth module by end of week.", hours=0),
        _email(2, "[task_2]", "Fix login redirect bug [task_2]",
               "Users report redirect loop after login. Fix ASAP.", hours=1),
    ]
    messages = [
        _message("Slack", "Alice", "Can you review PR #42?", minutes=30, ref="[task_3]"),
        _message("Slack", "Bob", "Thanks for the fix!", hours=2, minutes=15),
    ]
    notifications = []
    expected = {
        "top3_titles": ["Fix login redirect bug", "Refactor authentication module"],
        "focus_score_range": (0.85, 0.95),
        "recommendation": "Great focus day! Continue current pattern.",
    }
    return {"name": "successful_day", "tasks": tasks, "emails": emails,
            "messages": messages, "notifications": notifications, "expected": expected}


def dataset_distracted_day() -> dict:
    tasks = [
        _task("Prepare demo presentation", "email", 1, 4, 5, 3, "Stakeholder demo tomorrow", "[task_2]"),
        _task("Implement search feature", "email", 2, 4, 4, 3, "Core feature for sprint", "[task_1]"),
    ]
    emails = [
        _email(1, "[task_1]", "Implement search feature [task_1]", "We need search with filters.", hours=0),
        _email(2, "[task_2]", "Prepare demo presentation [task_2]", "Demo is tomorrow!", hours=0, minutes=30),
    ]
    messages = [
        _message("Slack", "Alice", "Hey, did you see the new design?", minutes=15),
        _message("Slack", "Bob", "Can you check this bug?", minutes=30),
        _message("Telegram", "Charlie", "Lunch plans?", hours=1),
        _message("Slack", "Dave", "URGENT: CI is broken!", hours=1, minutes=30, ref="[task_3]"),
        _message("Slack", "Eve", "Check this meme lol", hours=2),
        _message("Telegram", "Frank", "You there?", hours=2, minutes=15),
        _message("Slack", "Alice", "Meeting moved to 3pm", hours=2, minutes=45),
        _message("Slack", "Bob", "PR is ready for review", hours=3),
    ]
    notifications = [
        {"source": "Slack", "title": "New message from Alice", "body": "Hey, did you see the new design?",
         "requires_action": False, "has_deadline": False, "is_important": False, "related_to_task": False},
        {"source": "Telegram", "title": "Charlie", "body": "Lunch plans?",
         "requires_action": False, "has_deadline": False, "is_important": False, "related_to_task": False},
        {"source": "Slack", "title": "URGENT: CI broken", "body": "Dave: URGENT: CI is broken!",
         "requires_action": True, "has_deadline": True, "is_important": True, "related_to_task": True},
    ]
    expected = {
        "top3_titles": ["Prepare demo presentation", "Implement search feature"],
        "focus_score_range": (0.45, 0.65),
        "recommendation": "Consider tightening notification rules during focus sessions.",
    }
    return {"name": "distracted_day", "tasks": tasks, "emails": emails,
            "messages": messages, "notifications": notifications, "expected": expected}


def dataset_overloaded_day() -> dict:
    tasks = [
        _task("Database migration plan", "email", 1, 5, 5, 5, "Critical for Q3 release", "[task_1]"),
    ]
    emails = [
        _email(1, "[task_1]", "Database migration plan [task_1]", "Critical for Q3. Due tomorrow!", hours=0),
    ]
    messages = [
        _message("Slack", "Ops", "Production is down! Need hotfix NOW!", minutes=5, ref="[task_3]"),
        _message("Slack", "Manager", "Can we sync about the roadmap?", hours=1),
        _message("Slack", "Dev", "Tests are failing again", hours=2),
    ]
    notifications = [
        {"source": "Slack", "title": "Production down", "body": "Ops: Production is down!",
         "requires_action": True, "has_deadline": True, "is_important": True, "related_to_task": True},
        {"source": "Slack", "title": "Manager sync", "body": "Manager: Can we sync about the roadmap?",
         "requires_action": True, "has_deadline": False, "is_important": True, "related_to_task": False},
        {"source": "Slack", "title": "Tests failing", "body": "Dev: Tests are failing again",
         "requires_action": False, "has_deadline": False, "is_important": False, "related_to_task": False},
    ]
    expected = {
        "top3_titles": ["Database migration plan"],
        "focus_score_range": (0.20, 0.45),
        "recommendation": "Overloaded day — consider reducing task list or deferring non-critical items.",
    }
    return {"name": "overloaded_day", "tasks": tasks, "emails": emails,
            "messages": messages, "notifications": notifications, "expected": expected}


DATASETS["successful_day"] = dataset_successful_day
DATASETS["distracted_day"] = dataset_distracted_day
DATASETS["overloaded_day"] = dataset_overloaded_day


def get_dataset_names() -> list[str]:
    return list(DATASETS.keys())


def load_dataset(name: str) -> dict | None:
    fn = DATASETS.get(name)
    if not fn:
        return None
    return fn()
