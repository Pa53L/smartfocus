"""FocusScore: transparent, explainable 0-1 score for focus session quality."""

from __future__ import annotations

from models import FocusSession, FocusScoreBreakdown
from config import FS_WEIGHTS


def compute_focus_score(session: FocusSession) -> FocusScoreBreakdown:
    breakdown = FocusScoreBreakdown()
    total_duration = session.actual_duration if session.actual_duration > 0 else session.planned_duration
    if total_duration > 0:
        breakdown.focused_time_ratio = min(1.0, session.focused_time / total_duration)
    else:
        breakdown.focused_time_ratio = 0.0
    unplanned = [s for s in session.switches if s.is_distraction and not s.user_confirmed_working]
    total_switches = len(session.switches)
    if total_switches == 0:
        breakdown.switch_stability = 1.0
    else:
        breakdown.switch_stability = max(0.0, 1.0 - len(unplanned) / max(total_switches, 1))
    distraction_switches = [s for s in session.switches if s.is_distraction]
    if not distraction_switches:
        breakdown.recovery_rate = 1.0
    else:
        recovery_times = [s.recovery_seconds for s in distraction_switches if s.recovery_seconds > 0]
        if recovery_times:
            avg_recovery = sum(recovery_times) / len(recovery_times)
            breakdown.recovery_rate = max(0.0, 1.0 - avg_recovery / 300.0)
        else:
            breakdown.recovery_rate = 0.5
    breakdown.goal_progress = 1.0 if session.goal_achieved else 0.3
    breakdown.score = (
        FS_WEIGHTS["focused_time_ratio"] * breakdown.focused_time_ratio
        + FS_WEIGHTS["switch_stability"] * breakdown.switch_stability
        + FS_WEIGHTS["recovery_rate"] * breakdown.recovery_rate
        + FS_WEIGHTS["goal_progress"] * breakdown.goal_progress
    )
    breakdown.score = min(1.0, max(0.0, breakdown.score))
    return breakdown


def format_score_explanation(breakdown: FocusScoreBreakdown) -> str:
    lines = [
        f"FocusScore = {breakdown.score:.3f}",
        f"  0.55 x FTR = 0.55 x {breakdown.focused_time_ratio:.3f} = {0.55 * breakdown.focused_time_ratio:.3f}",
        f"  0.20 x SS  = 0.20 x {breakdown.switch_stability:.3f} = {0.20 * breakdown.switch_stability:.3f}",
        f"  0.15 x RR  = 0.15 x {breakdown.recovery_rate:.3f} = {0.15 * breakdown.recovery_rate:.3f}",
        f"  0.10 x GP  = 0.10 x {breakdown.goal_progress:.3f} = {0.10 * breakdown.goal_progress:.3f}",
    ]
    return "\n".join(lines)
