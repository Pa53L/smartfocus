"""Daily report generation — plan vs fact, FocusScore, recommendations."""

from __future__ import annotations

from datetime import datetime
import state


def generate_report(report_date: datetime | None = None) -> dict:
    """Generate a daily report from tasks and sessions."""
    report_date = report_date or datetime.now()
    date_str = report_date.strftime("%Y-%m-%d")
    tasks = state.get_tasks()
    sessions = state.get_sessions()
    # Filter sessions to this date
    today_sessions = [s for s in sessions
                      if (s.get("start_time", "")[:10] == date_str)]
    completed_tasks = [t for t in tasks if t.get("status") == "done"]
    incomplete = [t for t in tasks if t.get("status") == "pending"]
    stuck = [t for t in tasks if t.get("status") == "stuck"]
    carried_over = [t for t in tasks if t.get("status") == "carried_over"]
    completed_sessions = [s for s in today_sessions
                          if s.get("status") in ("completed", "auto_stopped")]
    auto_stopped_sessions = [s for s in today_sessions
                             if s.get("status") == "auto_stopped"]
    total_focused = sum(s.get("focused_time", 0) for s in completed_sessions)
    total_switches = sum(len(s.get("switches", [])) for s in completed_sessions)
    scores = [(s.get("focus_score") or 0) for s in completed_sessions if (s.get("focus_score") or 0) > 0]
    avg_score = sum(scores) / len(scores) if scores else 0

    distraction_sources: dict[str, int] = {}
    for s in completed_sessions:
        for sw in s.get("switches", []):
            if sw.get("is_distraction"):
                app = sw.get("to_app", "unknown")
                distraction_sources[app] = distraction_sources.get(app, 0) + 1

    best_hour = _find_best_hour(completed_sessions)

    # Cap title lists at 50 to prevent unbounded output
    completed_titles = [t.get("title", "") for t in completed_tasks][:50]
    incomplete_titles = [t.get("title", "") for t in incomplete][:50]
    stuck_titles = [t.get("title", "") for t in stuck][:50]

    report = {
        "date": date_str,
        "planned_tasks": len(tasks),
        "completed_tasks": len(completed_tasks),
        "incomplete_tasks": len(incomplete),
        "stuck_tasks": len(stuck),
        "carried_over_tasks": len(carried_over),
        "focus_sessions": len(completed_sessions),
        "auto_stopped_sessions": len(auto_stopped_sessions),
        "total_focused_minutes": round(total_focused, 1),
        "total_switches": total_switches,
        "distraction_sources": distraction_sources,
        "avg_focus_score": round(avg_score, 3),
        "best_focus_hour": best_hour,
        "completed_titles": completed_titles,
        "incomplete_titles": incomplete_titles,
        "stuck_titles": stuck_titles,
        "completed_count_total": len(completed_tasks),
        "incomplete_count_total": len(incomplete),
        "stuck_count_total": len(stuck),
        "omitted_completed": max(0, len(completed_tasks) - 50),
        "omitted_incomplete": max(0, len(incomplete) - 50),
        "omitted_stuck": max(0, len(stuck) - 50),
    }
    report["recommendation"] = _build_recommendation(report)
    report["next_day_recommendation"] = _build_next_day_recommendation(report, completed_sessions)
    state.log_action("report_generated", f"Report for {report['date']}: {report['completed_tasks']}/{report['planned_tasks']} tasks")
    return report


def _find_best_hour(sessions: list[dict]) -> str:
    time_scores: dict[int, list[float]] = {}
    for s in sessions:
        fs = s.get("focus_score", 0)
        if fs > 0 and s.get("start_time"):
            try:
                hour = datetime.fromisoformat(s["start_time"]).hour
                time_scores.setdefault(hour, []).append(fs)
            except (ValueError, TypeError):
                pass
    if not time_scores:
        return "09:00"
    best = max(time_scores, key=lambda h: sum(time_scores[h]) / len(time_scores[h]))
    return f"{best:02d}:00"


def _build_recommendation(report: dict) -> str:
    if report["avg_focus_score"] > 0.8 and report["completed_tasks"] >= report["planned_tasks"] * 0.8:
        return "Excellent day — maintain current workflow patterns."
    if report["total_switches"] > 20:
        return "High switch count — consider reducing distractions and batching notifications."
    if report["stuck_tasks"] > 2:
        return "Multiple stuck tasks — consider breaking them down or seeking help."
    if report["completed_tasks"] < report["planned_tasks"] * 0.5:
        return "Low completion rate — consider shorter sessions and fewer tasks per day."
    return "Balanced day — continue current approach with minor adjustments."


def _build_next_day_recommendation(report: dict, sessions: list[dict]) -> dict:
    """Build recommendations for the next day based on today's performance."""
    recommendations = []

    # Focus time recommendation
    focused_min = report.get("total_focused_minutes", 0)
    if focused_min < 60:
        recommendations.append("Aim for at least 2 focus sessions tomorrow (60+ min total).")
    elif focused_min < 120:
        recommendations.append("Good focus time — try adding one more session.")
    else:
        recommendations.append("Strong focus time — maintain this rhythm.")

    # Auto-stop analysis
    auto_stops = report.get("auto_stopped_sessions", 0)
    if auto_stops > 0:
        recommendations.append(
            f"{auto_stops} session(s) auto-stopped due to low focus — "
            "try shorter sessions or address distraction sources."
        )

    # Task carry-over
    carried = report.get("carried_over_tasks", 0)
    if carried > 3:
        recommendations.append(
            f"{carried} tasks carried over — prioritize Q1/Q2 tasks first tomorrow."
        )

    # Best time
    best_hour = report.get("best_focus_hour", "09:00")
    recommendations.append(f"Schedule complex tasks around {best_hour} — your best focus hour.")

    # Distraction sources
    distractions = report.get("distraction_sources", {})
    if distractions:
        top_distraction = max(distractions, key=distractions.get)
        recommendations.append(
            f"Top distraction: {top_distraction} ({distractions[top_distraction]} times) — "
            "consider blocking it during sessions."
        )

    # Recommended session duration from last session
    next_dur = 0
    if sessions:
        last = sessions[-1]
        next_dur = last.get("next_session_duration_min", 0)

    return {
        "summary": " | ".join(recommendations),
        "items": recommendations,
        "recommended_session_duration_min": next_dur,
        "recommended_focus_slots": f"Best at {best_hour}",
    }


def report_to_markdown(report: dict) -> str:
    lines = [
        f"# Daily Report — {report['date']}",
        "",
        "## Summary",
        f"- Planned tasks: {report['planned_tasks']}",
        f"- Completed: {report['completed_tasks']}",
        f"- Incomplete: {report['incomplete_tasks']}",
        f"- Stuck: {report['stuck_tasks']}",
        f"- Focus sessions: {report['focus_sessions']}",
        f"- Total focused time: {report['total_focused_minutes']} min",
        f"- Total switches: {report['total_switches']}",
        f"- Average FocusScore: {report['avg_focus_score']}",
        f"- Best focus hour: {report['best_focus_hour']}",
        "",
        "## Completed Tasks",
    ]
    for t in report.get("completed_titles", []):
        lines.append(f"- [x] {t}")
    lines.append("\n## Incomplete Tasks")
    for t in report.get("incomplete_titles", []):
        lines.append(f"- [ ] {t}")
    lines.append("\n## Stuck Tasks")
    for t in report.get("stuck_titles", []):
        lines.append(f"- [!] {t}")
    if report.get("distraction_sources"):
        lines.append("\n## Distraction Sources")
        for app, count in sorted(report["distraction_sources"].items(), key=lambda x: -x[1]):
            lines.append(f"- {app}: {count} times")
    lines.append(f"\n## Recommendation\n\n{report['recommendation']}")
    return "\n".join(lines)
