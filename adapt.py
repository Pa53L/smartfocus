"""Adaptation engine: learns from sessions and proposes recommendation changes."""

from __future__ import annotations

from datetime import datetime
from models import AdaptationProposal, FocusSession
import state


def analyze_sessions_and_propose(sessions: list[dict]) -> list[dict]:
    proposals = []
    if not sessions:
        return proposals
    completed = [s for s in sessions if s.get("status") == "completed"]
    completion_rate = len(completed) / len(sessions) if sessions else 0
    scores = [s.get("focus_score", 0) for s in completed if s.get("focus_score", 0) > 0]
    avg_score = sum(scores) / len(scores) if scores else 0
    total_switches = sum(len(s.get("switches", [])) for s in sessions)
    total_distractions = sum(
        len([sw for sw in s.get("switches", []) if sw.get("is_distraction")]) for s in sessions
    )

    if completion_rate < 0.3:
        p = AdaptationProposal(
            observation=f"Low completion rate: {completion_rate:.0%} of sessions completed",
            rationale="Users with low completion rates benefit from shorter sessions",
            proposed_change="Reduce default session duration from 25 to 15-20 minutes",
        )
        proposals.append(p.to_dict())
        state.add_proposal(p.to_dict())
    elif completion_rate > 0.8 and avg_score > 0.8:
        p = AdaptationProposal(
            observation=f"High completion ({completion_rate:.0%}) and FocusScore ({avg_score:.2f})",
            rationale="User handles longer sessions well",
            proposed_change="Consider increasing default session duration to 35-40 minutes",
        )
        proposals.append(p.to_dict())
        state.add_proposal(p.to_dict())

    if total_distractions > total_switches * 0.5 and total_switches > 5:
        p = AdaptationProposal(
            observation=f"High distraction ratio: {total_distractions}/{total_switches} switches",
            rationale="More than half of app switches are distractions",
            proposed_change="Defer all non-urgent notifications during focus sessions by default",
        )
        proposals.append(p.to_dict())
        state.add_proposal(p.to_dict())

    time_scores: dict[int, list[float]] = {}
    for s in completed:
        fs = s.get("focus_score", 0)
        if fs > 0 and s.get("start_time"):
            try:
                hour = datetime.fromisoformat(s["start_time"]).hour
                time_scores.setdefault(hour, []).append(fs)
            except (ValueError, TypeError):
                pass
    if time_scores:
        best_hour = max(time_scores, key=lambda h: sum(time_scores[h]) / len(time_scores[h]))
        current_best = state.get_setting("best_time_for_complex_tasks", "09:00")
        proposed_time = f"{best_hour:02d}:00"
        if proposed_time != current_best:
            p = AdaptationProposal(
                observation=f"Best FocusScore consistently at {proposed_time}",
                rationale=f"Average score: {sum(time_scores[best_hour])/len(time_scores[best_hour]):.2f}",
                proposed_change=f"Update best_time_for_complex_tasks to '{proposed_time}'",
            )
            proposals.append(p.to_dict())
            state.add_proposal(p.to_dict())

    for p in proposals:
        state.log_action("adaptation_proposal", f"{p['observation']} -> {p['proposed_change']}")
    return proposals


def accept_proposal(proposal_id: str) -> dict | None:
    proposals = state.get_proposals()
    for p in proposals:
        if p.get("id") == proposal_id:
            change = p.get("proposed_change", "")
            import re
            m = re.search(r"to '(\d{2}:\d{2})'", change)
            if m:
                state.set_setting("best_time_for_complex_tasks", m.group(1))
            state.update_proposal(proposal_id, {
                "status": "accepted",
                "applied_at": datetime.now().isoformat(),
            })
            state.log_action("adaptation_applied", change)
            updated = {k: v for k, v in p.items()}
            updated["status"] = "accepted"
            updated["applied_at"] = datetime.now().isoformat()
            return updated
    return None


def reject_proposal(proposal_id: str) -> bool:
    return state.update_proposal(proposal_id, {"status": "rejected"})


def get_proposals(status: str | None = None) -> list[dict]:
    return state.get_proposals(status)


def recommend_next_session(last_session: dict) -> int:
    """Recommend duration for the next focus session based on the last session's result.

    Logic:
    - If last session had high focus score (>0.8) and was completed → suggest slightly longer
    - If last session had low score (<0.5) → suggest shorter
    - If last session was auto-stopped → suggest significantly shorter
    - Otherwise → keep the same duration
    """
    from config import SESSION_MIN_MINUTES, SESSION_MAX_MINUTES

    last_dur = int(last_session.get("planned_duration", 25))
    score = last_session.get("focus_score", 0)
    status = last_session.get("status", "completed")
    actual = last_session.get("actual_duration", 0)

    if status == "auto_stopped":
        # Focus dropped — recommend a shorter session
        recommended = max(SESSION_MIN_MINUTES, last_dur - 10)
    elif score > 0.8:
        # Excellent focus — can handle slightly longer
        recommended = min(SESSION_MAX_MINUTES, last_dur + 5)
    elif score < 0.5:
        # Poor focus — shorter session
        recommended = max(SESSION_MIN_MINUTES, last_dur - 5)
    else:
        # Moderate — keep similar duration
        recommended = last_dur

    # Factor in actual duration vs planned
    if actual > 0 and actual < last_dur * 0.7:
        # Session ended early — suggest shorter next time
        recommended = max(SESSION_MIN_MINUTES, int(actual) + 5)

    return max(SESSION_MIN_MINUTES, min(SESSION_MAX_MINUTES, recommended))
