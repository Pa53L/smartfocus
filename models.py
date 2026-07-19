"""SmartFocus data models — pure Python dataclasses, no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CARRIED_OVER = "carried_over"
    STUCK = "stuck"


class TaskSource(str, Enum):
    EMAIL = "email"
    MESSAGE = "message"
    CALENDAR = "calendar"
    MANUAL = "manual"
    SYNTHETIC = "synthetic"


class NotificationAction(str, Enum):
    SHOW_NOW = "show_now"
    DEFER = "defer"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    AUTO_STOPPED = "auto_stopped"


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    source: TaskSource = TaskSource.SYNTHETIC
    source_ref: str = ""
    deadline: Optional[datetime] = None
    importance: int = 3
    urgency: int = 3
    complexity: int = 3
    quadrant: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority_score: float = 0.0
    priority_explanation: str = ""
    recommended_start: Optional[datetime] = None
    recommended_duration: int = 25
    linked_email_id: Optional[str] = None
    linked_message_id: Optional[str] = None
    day_goal_link: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def compute_quadrant(self):
        if self.urgency >= 4 and self.importance >= 4:
            self.quadrant = "Q1"
        elif self.urgency < 4 and self.importance >= 4:
            self.quadrant = "Q2"
        elif self.urgency >= 4 and self.importance < 4:
            self.quadrant = "Q3"
        else:
            self.quadrant = "Q4"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source.value,
            "source_ref": self.source_ref,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "importance": self.importance,
            "urgency": self.urgency,
            "complexity": self.complexity,
            "quadrant": self.quadrant,
            "status": self.status.value,
            "priority_score": self.priority_score,
            "priority_explanation": self.priority_explanation,
            "recommended_start": self.recommended_start.isoformat() if self.recommended_start else None,
            "recommended_duration": self.recommended_duration,
            "day_goal_link": self.day_goal_link,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        t = cls()
        t.id = d.get("id", str(uuid.uuid4()))
        t.title = d.get("title", "")
        t.source = TaskSource(d.get("source", "synthetic"))
        t.source_ref = d.get("source_ref", "")
        if d.get("deadline"):
            try:
                parsed = datetime.fromisoformat(d["deadline"])
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                t.deadline = parsed
            except (ValueError, TypeError):
                pass
        t.importance = d.get("importance", 3)
        t.urgency = d.get("urgency", 3)
        t.complexity = d.get("complexity", 3)
        t.quadrant = d.get("quadrant", "")
        t.status = TaskStatus(d.get("status", "pending"))
        t.priority_score = d.get("priority_score", 0.0)
        t.priority_explanation = d.get("priority_explanation", "")
        if d.get("recommended_start"):
            try:
                t.recommended_start = datetime.fromisoformat(d["recommended_start"])
            except (ValueError, TypeError):
                pass
        t.recommended_duration = d.get("recommended_duration", 25)
        t.day_goal_link = d.get("day_goal_link", "")
        if d.get("created_at"):
            try:
                t.created_at = datetime.fromisoformat(d["created_at"])
            except (ValueError, TypeError):
                pass
        if d.get("completed_at"):
            try:
                t.completed_at = datetime.fromisoformat(d["completed_at"])
            except (ValueError, TypeError):
                pass
        return t


@dataclass
class ActivityEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    app_name: str = ""
    duration_seconds: float = 0.0
    is_related_to_task: bool = True
    is_distraction: bool = False
    distraction_reason: str = ""


@dataclass
class AppSwitch:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    from_app: str = ""
    to_app: str = ""
    is_planned: bool = False
    is_distraction: bool = False
    recovery_seconds: float = 0.0
    user_confirmed_working: bool = False

    def to_dict(self) -> dict:
        return {
            "from_app": self.from_app,
            "to_app": self.to_app,
            "is_planned": self.is_planned,
            "is_distraction": self.is_distraction,
            "recovery_seconds": self.recovery_seconds,
            "user_confirmed_working": self.user_confirmed_working,
        }


@dataclass
class Notification:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""
    title: str = ""
    body: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    requires_action: bool = False
    has_deadline: bool = False
    is_important: bool = False
    related_to_current_task: bool = False
    action: NotificationAction = NotificationAction.DEFER
    action_explanation: str = ""
    shown: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "requires_action": self.requires_action,
            "has_deadline": self.has_deadline,
            "is_important": self.is_important,
            "related_to_current_task": self.related_to_current_task,
            "action": self.action.value,
            "action_explanation": self.action_explanation,
            "shown": self.shown,
        }


@dataclass
class FocusSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    task_title: str = ""
    goal: str = ""
    expected_result: str = ""
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    planned_duration: int = 25
    actual_duration: float = 0.0
    focused_time: float = 0.0
    readiness: int = 3
    time_to_next_meeting: int = 60
    allowed_apps: list = field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
    activities: list = field(default_factory=list)
    switches: list = field(default_factory=list)
    notifications: list = field(default_factory=list)
    focus_score: float = 0.0
    focus_score_breakdown: dict = field(default_factory=dict)
    goal_achieved: bool = False
    feedback: dict = field(default_factory=dict)
    # New fields for scenario support
    task_status: str = ""  # completed/break/deferred when stopping
    work_tools: list = field(default_factory=list)  # tools needed for this task
    focus_checks: list = field(default_factory=list)  # intermediate score checks
    next_session_duration_min: int = 0  # recommended duration for next session
    notification_summary: dict = field(default_factory=dict)  # summary of notifications during session

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "goal": self.goal,
            "expected_result": self.expected_result,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "planned_duration": self.planned_duration,
            "actual_duration": round(self.actual_duration, 1),
            "focused_time": round(self.focused_time, 1),
            "readiness": self.readiness,
            "time_to_next_meeting": self.time_to_next_meeting,
            "allowed_apps": self.allowed_apps,
            "status": self.status.value,
            "activities": self.activities,
            "switches": [s.to_dict() for s in self.switches],
            "notifications": [n.to_dict() for n in self.notifications],
            "focus_score": round(self.focus_score, 3),
            "focus_score_breakdown": self.focus_score_breakdown,
            "goal_achieved": self.goal_achieved,
            "feedback": self.feedback,
            "task_status": self.task_status,
            "work_tools": self.work_tools,
            "focus_checks": self.focus_checks,
            "next_session_duration_min": self.next_session_duration_min,
            "notification_summary": self.notification_summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FocusSession":
        s = cls()
        s.id = d.get("id", str(uuid.uuid4()))
        s.task_id = d.get("task_id", "")
        s.task_title = d.get("task_title", "")
        s.goal = d.get("goal", "")
        s.expected_result = d.get("expected_result", "")
        if d.get("start_time"):
            try:
                s.start_time = datetime.fromisoformat(d["start_time"])
            except (ValueError, TypeError):
                pass
        if d.get("end_time"):
            try:
                s.end_time = datetime.fromisoformat(d["end_time"])
            except (ValueError, TypeError):
                pass
        s.planned_duration = d.get("planned_duration", 25)
        s.actual_duration = d.get("actual_duration", 0.0)
        s.focused_time = d.get("focused_time", 0.0)
        s.readiness = d.get("readiness", 3)
        s.time_to_next_meeting = d.get("time_to_next_meeting", 60)
        s.allowed_apps = d.get("allowed_apps", [])
        s.status = SessionStatus(d.get("status", "active"))
        s.focus_score = d.get("focus_score", 0.0)
        s.focus_score_breakdown = d.get("focus_score_breakdown", {})
        s.goal_achieved = d.get("goal_achieved", False)
        s.feedback = d.get("feedback", {})
        s.task_status = d.get("task_status", "")
        s.work_tools = d.get("work_tools", [])
        s.focus_checks = d.get("focus_checks", [])
        s.next_session_duration_min = d.get("next_session_duration_min", 0)
        s.notification_summary = d.get("notification_summary", {})
        # Rehydrate nested lists so stop_session scoring has full data
        s.switches = [AppSwitch(
            from_app=sw.get("from_app", ""),
            to_app=sw.get("to_app", ""),
            is_planned=sw.get("is_planned", False),
            is_distraction=sw.get("is_distraction", False),
            recovery_seconds=sw.get("recovery_seconds", 0.0),
            user_confirmed_working=sw.get("user_confirmed_working", False),
        ) for sw in d.get("switches", [])]
        s.activities = list(d.get("activities", []))
        s.notifications = list(d.get("notifications", []))
        return s


@dataclass
class FocusScoreBreakdown:
    focused_time_ratio: float = 0.0
    switch_stability: float = 0.0
    recovery_rate: float = 0.0
    goal_progress: float = 0.0
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "focused_time_ratio": round(self.focused_time_ratio, 4),
            "switch_stability": round(self.switch_stability, 4),
            "recovery_rate": round(self.recovery_rate, 4),
            "goal_progress": round(self.goal_progress, 4),
            "score": round(self.score, 4),
        }


@dataclass
class KnowledgeEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    task_id: str = ""
    question: str = ""
    answer: str = ""
    summary: str = ""
    markdown_path: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "question": self.question,
            "answer": self.answer,
            "summary": self.summary,
            "markdown_path": self.markdown_path,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AdaptationProposal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    observation: str = ""
    rationale: str = ""
    proposed_change: str = ""
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    applied_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "observation": self.observation,
            "rationale": self.rationale,
            "proposed_change": self.proposed_change,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AdaptationProposal":
        p = cls()
        p.id = d.get("id", str(uuid.uuid4()))
        p.observation = d.get("observation", "")
        p.rationale = d.get("rationale", "")
        p.proposed_change = d.get("proposed_change", "")
        p.status = d.get("status", "pending")
        if d.get("created_at"):
            try:
                p.created_at = datetime.fromisoformat(d["created_at"])
            except (ValueError, TypeError):
                pass
        if d.get("applied_at"):
            try:
                p.applied_at = datetime.fromisoformat(d["applied_at"])
            except (ValueError, TypeError):
                pass
        return p
