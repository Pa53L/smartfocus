"""Focus session lifecycle: start, track activity, switch apps, complete."""

from __future__ import annotations

from datetime import datetime
from models import FocusSession, ActivityEntry, AppSwitch, SessionStatus, Notification
from focus_score import compute_focus_score
from config import (
    SESSION_MIN_MINUTES, SESSION_MAX_MINUTES, SESSION_DEFAULT_MINUTES,
    DISTRACTION_APPS, DEFAULT_ALLOWED_APPS, DND_ENABLED_DEFAULT,
)
import state
import json


def _toggle_dnd(enable: bool) -> bool:
    """Toggle macOS Do Not Disturb. Returns True on success."""
    try:
        import dnd
        if enable:
            return dnd.enable_dnd()
        else:
            return dnd.disable_dnd()
    except Exception:
        return False


def recommend_duration(readiness: int, complexity: int, time_to_meeting: int,
                       history_completion_rate: float = 0.5) -> int:
    base = SESSION_DEFAULT_MINUTES
    if readiness >= 4:
        base += 10
    elif readiness <= 2:
        base -= 10
    if complexity >= 4:
        base += 5
    elif complexity <= 2:
        base -= 5
    if time_to_meeting < base:
        base = max(SESSION_MIN_MINUTES, time_to_meeting - 5)
    if history_completion_rate < 0.3:
        base -= 5
    return max(SESSION_MIN_MINUTES, min(SESSION_MAX_MINUTES, base))


def start_session(task_id: str, goal: str, expected_result: str,
                  allowed_apps: list[str] | None = None,
                  readiness: int = 3, time_to_next_meeting: int = 60,
                  recommended_duration: int | None = None,
                  task_title: str = "",
                  work_tools: list[str] | None = None) -> dict:
    # Guard: reject empty task_id or goal (prevents ghost sessions)
    if not task_id or not task_id.strip() or not goal or not goal.strip():
        return {"error": "task_id and goal are required"}
    # Guard: reject if a session is already active
    existing = state.get_active_session()
    if existing:
        return {"error": "A focus session is already active. Stop it first.",
                "active_session_id": existing.get("id", "")}
    if not allowed_apps:
        allowed_apps = state.get_setting("allowed_apps", DEFAULT_ALLOWED_APPS)
    if recommended_duration is None:
        recommended_duration = recommend_duration(readiness, 3, time_to_next_meeting)
    session = FocusSession(
        task_id=task_id,
        task_title=task_title,
        goal=goal,
        expected_result=expected_result,
        start_time=datetime.now(),
        planned_duration=recommended_duration,
        readiness=readiness,
        time_to_next_meeting=time_to_next_meeting,
        allowed_apps=allowed_apps,
        status=SessionStatus.ACTIVE,
        work_tools=work_tools or [],
    )
    state.append_session(session.to_dict())
    state.log_action("session_start",
                     f"Task {task_id}, goal: {goal}, duration: {recommended_duration}min, "
                     f"work_tools: {work_tools or []}")

    # Enable Do Not Disturb if configured
    dnd_enabled = state.get_setting("enable_dnd_on_session", True)
    dnd_result = "skipped"
    if dnd_enabled:
        dnd_ok = _toggle_dnd(True)
        dnd_result = "enabled" if dnd_ok else "failed"
        state.log_action("dnd_toggle", f"enable: {dnd_result}")

    result = session.to_dict()
    result["dnd_status"] = dnd_result
    return result


def get_active_session() -> dict | None:
    return state.get_active_session()


def stop_session(goal_achieved: bool = False, feedback: dict | None = None,
                 task_status: str = "") -> dict | None:
    active = state.get_active_session()
    if not active:
        return None
    session = FocusSession.from_dict(active)
    session.end_time = datetime.now()
    session.actual_duration = (session.end_time - session.start_time).total_seconds() / 60.0
    session.goal_achieved = goal_achieved
    session.feedback = feedback or {}
    session.status = SessionStatus.COMPLETED
    session.task_status = task_status
    breakdown = compute_focus_score(session)
    session.focus_score = breakdown.score
    session.focus_score_breakdown = breakdown.to_dict()

    # Update task status based on session outcome
    if task_status == "completed":
        state.update_task_status(session.task_id, "done")
    elif task_status == "deferred":
        state.update_task_status(session.task_id, "carried_over")
    # "break" — task stays in_progress, no status change needed

    # Recommend next session duration based on this session's result
    try:
        import adapt
        next_dur = adapt.recommend_next_session(session.to_dict())
        session.next_session_duration_min = next_dur
    except Exception:
        session.next_session_duration_min = 0

    # Generate notification summary
    try:
        import notifications as notif_mod
        session.notification_summary = notif_mod.generate_session_notification_summary(session.id)
    except Exception:
        session.notification_summary = {}

    state.update_session_by_id(session.id, session.to_dict())
    state.log_action("session_complete",
                     f"Duration: {session.actual_duration:.1f}min, Score: {session.focus_score:.3f}, "
                     f"task_status: {task_status}, next_dur: {session.next_session_duration_min}min")

    # Disable Do Not Disturb
    dnd_enabled = state.get_setting("enable_dnd_on_session", True)
    dnd_result = "skipped"
    if dnd_enabled:
        dnd_ok = _toggle_dnd(False)
        dnd_result = "disabled" if dnd_ok else "failed"
        state.log_action("dnd_toggle", f"disable: {dnd_result}")

    # Attach emails received during this session
    session_emails = state.get_session_emails(session.id)

    result = session.to_dict()
    result["dnd_status"] = dnd_result
    result["emails_during_session"] = session_emails
    result["emails_count"] = len(session_emails)
    return result


def auto_stop_session(reason: str = "focus_score_below_threshold") -> dict | None:
    """Auto-stop the active session (called by companion when focus score drops)."""
    active = state.get_active_session()
    if not active:
        return None
    session = FocusSession.from_dict(active)
    session.end_time = datetime.now()
    session.actual_duration = (session.end_time - session.start_time).total_seconds() / 60.0
    session.goal_achieved = False
    session.status = SessionStatus.AUTO_STOPPED
    session.feedback = {"auto_stop_reason": reason}
    breakdown = compute_focus_score(session)
    session.focus_score = breakdown.score
    session.focus_score_breakdown = breakdown.to_dict()

    try:
        import adapt
        next_dur = adapt.recommend_next_session(session.to_dict())
        session.next_session_duration_min = next_dur
    except Exception:
        session.next_session_duration_min = 0

    try:
        import notifications as notif_mod
        session.notification_summary = notif_mod.generate_session_notification_summary(session.id)
    except Exception:
        session.notification_summary = {}

    state.update_session_by_id(session.id, session.to_dict())
    state.log_action("session_auto_stopped",
                     f"Reason: {reason}, Score: {session.focus_score:.3f}, "
                     f"Duration: {session.actual_duration:.1f}min")

    # Disable DND
    dnd_enabled = state.get_setting("enable_dnd_on_session", True)
    if dnd_enabled:
        _toggle_dnd(False)

    result = session.to_dict()
    result["auto_stopped"] = True
    result["auto_stop_reason"] = reason
    return result


def compute_intermediate_focus_score(session_id: str) -> dict | None:
    """Compute focus score for an active session without stopping it.
    Stores the check in session.focus_checks for later analysis."""
    active = state.get_active_session()
    if not active or active.get("id") != session_id:
        return None
    session = FocusSession.from_dict(active)
    breakdown = compute_focus_score(session)

    check_entry = {
        "timestamp": datetime.now().isoformat(),
        "score": round(breakdown.score, 4),
        "breakdown": breakdown.to_dict(),
    }

    def _modifier(s: dict) -> dict:
        if "focus_checks" not in s:
            s["focus_checks"] = []
        s["focus_checks"].append(check_entry)
        return check_entry

    state.modify_session(session_id, _modifier)
    return check_entry


def propose_focus_slots(available_hours: float = 8.0,
                        calendar_events: list[dict] | None = None) -> dict:
    """Propose focus work slots based on calendar and session history.

    Uses past session FocusScores by hour to find optimal focus times,
    and avoids overlapping with calendar events.
    """
    from config import SESSION_MIN_MINUTES, SESSION_MAX_MINUTES, SESSION_DEFAULT_MINUTES

    sessions = state.get_sessions()
    completed = [s for s in sessions if s.get("status") in ("completed", "auto_stopped")]

    # Build hour→avg_score map from session history
    hour_scores: dict[int, list[float]] = {}
    for s in completed:
        fs = s.get("focus_score", 0)
        start = s.get("start_time", "")
        if fs > 0 and start:
            try:
                hour = datetime.fromisoformat(start).hour
                hour_scores.setdefault(hour, []).append(fs)
            except (ValueError, TypeError):
                pass

    # Find best hours (sorted by avg score descending)
    best_hours = sorted(
        hour_scores.keys(),
        key=lambda h: sum(hour_scores[h]) / len(hour_scores[h]),
        reverse=True,
    ) if hour_scores else [9, 10, 14]

    # Build proposed slots
    slots = []
    calendar_events = calendar_events or []

    # Default working hours: 9:00 to 18:00
    work_start_hour = 9
    work_end_hour = 18

    # Generate slots from best hours first
    for hour in best_hours[:6]:
        if hour < work_start_hour or hour >= work_end_hour:
            continue
        slot_start = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
        slot_end = slot_start.replace(hour=hour + 1)

        # Check calendar conflicts
        conflict = False
        for event in calendar_events:
            try:
                ev_start = datetime.fromisoformat(event.get("start", ""))
                ev_end = datetime.fromisoformat(event.get("end", ""))
                if slot_start < ev_end and slot_end > ev_start:
                    conflict = True
                    break
            except (ValueError, TypeError):
                continue

        if conflict:
            continue

        # Recommend duration based on history
        duration = SESSION_DEFAULT_MINUTES
        if completed:
            last = completed[-1]
            last_dur = last.get("next_session_duration_min", 0)
            if last_dur > 0:
                duration = max(SESSION_MIN_MINUTES, min(SESSION_MAX_MINUTES, last_dur))

        avg_score = (sum(hour_scores[hour]) / len(hour_scores[hour])
                     if hour in hour_scores else 0)

        slots.append({
            "start": slot_start.isoformat(),
            "end": slot_end.isoformat(),
            "recommended_duration_min": duration,
            "avg_focus_score": round(avg_score, 3) if avg_score else None,
            "reason": (f"Best historical FocusScore at {hour:02d}:00"
                       if hour in hour_scores
                       else "Default productive hour"),
        })

    return {
        "proposed_slots": slots[:5],
        "total_sessions_analyzed": len(completed),
        "best_time": f"{best_hours[0]:02d}:00" if best_hours else "09:00",
        "calendar_events_count": len(calendar_events),
    }


def record_activity(session_id: str, app_name: str, duration_seconds: float,
                    is_related: bool = True) -> dict | None:
    def _modifier(s: dict) -> dict:
        is_distraction = app_name in DISTRACTION_APPS and not is_related
        entry = {
            "app_name": app_name,
            "duration_seconds": duration_seconds,
            "is_related_to_task": is_related,
            "is_distraction": is_distraction,
        }
        if "activities" not in s:
            s["activities"] = []
        s["activities"].append(entry)
        if is_related:
            s["focused_time"] = s.get("focused_time", 0.0) + duration_seconds / 60.0
        return entry
    return state.modify_session(session_id, _modifier)


def record_switch(session_id: str, from_app: str, to_app: str,
                  is_planned: bool = False) -> dict | None:
    def _modifier(s: dict) -> dict:
        is_distraction = to_app in DISTRACTION_APPS and not is_planned
        sw = AppSwitch(
            session_id=session_id,
            from_app=from_app,
            to_app=to_app,
            is_planned=is_planned,
            is_distraction=is_distraction,
        )
        if "switches" not in s:
            s["switches"] = []
        s["switches"].append(sw.to_dict())
        return sw.to_dict()
    result = state.modify_session(session_id, _modifier)
    if result is not None:
        state.log_action("app_switch", f"{from_app} -> {to_app}, distraction={result.get('is_distraction', False)}")
    return result


def get_session_summary(session_dict: dict) -> dict:
    switches = session_dict.get("switches", [])
    distractions = [s for s in switches if s.get("is_distraction")]
    recovery_times = [s.get("recovery_seconds", 0) for s in distractions if s.get("recovery_seconds", 0) > 0]
    avg_recovery = sum(recovery_times) / len(recovery_times) if recovery_times else 0
    return {
        "session_id": session_dict.get("id", ""),
        "task_id": session_dict.get("task_id", ""),
        "goal": session_dict.get("goal", ""),
        "planned_duration": session_dict.get("planned_duration", 0),
        "actual_duration": round(session_dict.get("actual_duration", 0.0), 1),
        "focused_time": round(session_dict.get("focused_time", 0.0), 1),
        "switch_count": len(switches),
        "distraction_count": len(distractions),
        "avg_recovery_seconds": round(avg_recovery, 1),
        "goal_achieved": session_dict.get("goal_achieved", False),
        "focus_score": round(session_dict.get("focus_score", 0.0), 3),
        "focus_score_breakdown": session_dict.get("focus_score_breakdown", {}),
    }


def get_session_elapsed_minutes(session_dict: dict) -> float:
    start_str = session_dict.get("start_time")
    if not start_str:
        return 0.0
    try:
        start = datetime.fromisoformat(start_str)
        return (datetime.now() - start).total_seconds() / 60.0
    except (ValueError, TypeError):
        return 0.0
