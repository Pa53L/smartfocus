"""Prioritization engine: Eisenhower matrix + deterministic scoring + TOP-3."""

from __future__ import annotations

from datetime import datetime, timedelta
from models import Task
from config import PRIO_WEIGHTS
import state


def compute_priority_score(task: Task, now: datetime | None = None,
                           available_hours: float = 8.0) -> float:
    now = now or datetime.now()
    if task.deadline:
        days_left = (task.deadline - now).total_seconds() / 86400
        if days_left <= 0:
            deadline_score = 1.0
        elif days_left <= 1:
            deadline_score = 0.95
        elif days_left <= 3:
            deadline_score = 0.80
        elif days_left <= 7:
            deadline_score = 0.60
        else:
            deadline_score = max(0.1, 1.0 - days_left / 30)
    else:
        deadline_score = 0.3
    urgency_score = (task.urgency - 1) / 4.0
    influence_score = (task.importance - 1) / 4.0
    goal_link_score = 1.0 if task.day_goal_link else 0.3
    cost_score = 1.0 - (task.complexity - 1) / 8.0
    repeat_score = 0.7 if task.source_ref else 0.3
    complexity_score = 1.0 - (task.complexity - 1) / 4.0
    estimated_time = task.complexity * 0.5
    time_fit = 1.0 if estimated_time <= available_hours else max(0.1, available_hours / estimated_time)
    score = (
        PRIO_WEIGHTS["deadline_proximity"] * deadline_score
        + PRIO_WEIGHTS["explicit_urgency"] * urgency_score
        + PRIO_WEIGHTS["task_influence"] * influence_score
        + PRIO_WEIGHTS["day_goal_link"] * goal_link_score
        + PRIO_WEIGHTS["non_execution_cost"] * cost_score
        + PRIO_WEIGHTS["repeat_reminders"] * repeat_score
        + PRIO_WEIGHTS["complexity"] * complexity_score
        + PRIO_WEIGHTS["available_time"] * time_fit
    )
    return min(1.0, max(0.0, score))


def explain_priority(task: Task, score: float, now: datetime | None = None) -> str:
    now = now or datetime.now()
    reasons = []
    if task.deadline:
        days_left = (task.deadline - now).days
        if days_left <= 0:
            reasons.append("Deadline is today or overdue")
        elif days_left <= 1:
            reasons.append(f"Deadline in {days_left + 1} day(s)")
        elif days_left <= 3:
            reasons.append(f"Deadline in {days_left} days")
        else:
            reasons.append(f"Deadline in {days_left} days")
    if task.urgency >= 4:
        reasons.append(f"High urgency ({task.urgency}/5)")
    if task.importance >= 4:
        reasons.append(f"High importance ({task.importance}/5)")
    if task.day_goal_link:
        reasons.append(f"Linked to day goal: {task.day_goal_link}")
    if task.complexity >= 4:
        reasons.append(f"Complex task ({task.complexity}/5)")
    if task.source_ref:
        reasons.append(f"Referenced in {task.source_ref}")
    q_names = {
        "Q1": "Urgent + Important — do first",
        "Q2": "Important, not urgent — schedule",
        "Q3": "Urgent, not important — delegate if possible",
        "Q4": "Not urgent, not important — low priority",
    }
    q_name = q_names.get(task.quadrant, "Unclassified")
    reasons.append(f"Eisenhower: {task.quadrant} ({q_name})")
    return " | ".join(reasons) + f" | Score: {score:.3f}"


def prioritize(tasks: list[Task], now: datetime | None = None,
               available_hours: float = 8.0) -> list[Task]:
    now = now or datetime.now()
    for t in tasks:
        t.compute_quadrant()
        t.priority_score = compute_priority_score(t, now, available_hours)
        t.priority_explanation = explain_priority(t, t.priority_score, now)
    sorted_tasks = sorted(tasks, key=lambda t: t.priority_score, reverse=True)
    current_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    for t in sorted_tasks:
        t.recommended_start = current_time
        t.recommended_duration = max(15, min(50, t.complexity * 10 + 15))
        current_time = current_time + timedelta(minutes=t.recommended_duration + 5)
    if sorted_tasks:
        state.log_action("prioritize",
                         f"Prioritized {len(tasks)} tasks, top: {sorted_tasks[0].priority_score:.3f}")
    return sorted_tasks


def get_top3(tasks: list[Task]) -> list[Task]:
    return tasks[:3]


def get_eisenhower_matrix(tasks: list[Task]) -> dict:
    for t in tasks:
        t.compute_quadrant()
    matrix = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for t in tasks:
        matrix.setdefault(t.quadrant, []).append(t)
    for q in matrix:
        matrix[q] = sorted(matrix[q], key=lambda t: t.priority_score, reverse=True)
    return matrix


def matrix_to_markdown(matrix: dict) -> str:
    lines = ["## Eisenhower Matrix\n"]
    q_names = {
        "Q1": "Q1 — Urgent + Important (Do First)",
        "Q2": "Q2 — Important, Not Urgent (Schedule)",
        "Q3": "Q3 — Urgent, Not Important (Delegate)",
        "Q4": "Q4 — Not Urgent, Not Important (Eliminate)",
    }
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        lines.append(f"### {q_names[q]}")
        items = matrix.get(q, [])
        if items:
            for t in items:
                lines.append(f"- **{t.title}** (score: {t.priority_score:.3f}) — {t.priority_explanation}")
        else:
            lines.append("- *(empty)*")
        lines.append("")
    return "\n".join(lines)
