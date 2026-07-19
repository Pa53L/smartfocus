"""SmartFocus companion process — proactive session monitoring, email polling, and nudges.

Runs as a host-supervised subprocess declared in the manifest.

Cycles every 30 seconds:
  - Check if active session is past planned duration → nudge
  - Every 3 minutes: scan Thunderbird INBOX for new emails
    - Extract [task-XXX] from subjects → nudge about new tasks
    - If session is active, store emails as session emails for the report

Sends nudges via the Host Service API (POST /chat/inject).

Env vars provided by the host:
  HOST_SERVICE_URL  — loopback Host Service base URL
  HOST_SERVICE_TOKEN — opaque skill token for auth
  OUROBOROS_SKILL_STATE_DIR — canonical state directory
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# Allow importing sibling skill modules
_SKILL_DIR = pathlib.Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

import state

POLL_INTERVAL_SEC = 30
NUDGE_COOLDOWN_SEC = 300
EMAIL_SCAN_INTERVAL_SEC = 180  # 3 minutes
FOCUS_CHECK_INTERVAL_SEC = 300  # 5 minutes between focus score checks
FOCUS_SCORE_THRESHOLD = 0.6     # auto-stop if below this

# Preflight results — set once in main(), checked in loop functions
_email_available: bool = True
_activity_available: bool = True


def _state_dir() -> str:
    return os.environ.get("OUROBOROS_SKILL_STATE_DIR", "")


def _host_url() -> str:
    """Return Host Service URL, enforcing loopback-only for token safety."""
    raw = os.environ.get("HOST_SERVICE_URL", "http://127.0.0.1:8767")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in ("localhost", "127.0.0.1", "::1"):
            sys.stderr.write(f"[smartfocus] HOST_SERVICE_URL host '{host}' is not loopback — falling back to default\n")
            return "http://127.0.0.1:8767"
    except Exception:
        return "http://127.0.0.1:8767"
    return raw


def _host_token() -> str:
    return os.environ.get("HOST_SERVICE_TOKEN", "")


def _send_nudge(message: str) -> bool:
    """Send a chat nudge via the Host Service API."""
    url = _host_url().rstrip("/") + "/chat/inject"
    token = _host_token()
    if not token:
        return False
    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "X-Skill-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        sys.stderr.write(f"[smartfocus] nudge failed: {e}\n")
        return False


# ─── Session timer check ──────────────────────────────


def _check_session() -> str | None:
    """Check active session state; return a nudge message or None."""
    sd = _state_dir()
    if not sd:
        return None
    active = state.get_active_session()
    if not active:
        return None

    now = datetime.now()
    try:
        start = datetime.fromisoformat(active["start_time"])
        elapsed_min = (now - start).total_seconds() / 60.0
    except (ValueError, TypeError, KeyError):
        return None
    planned = active.get("planned_duration", 25)
    task_title = active.get("task_title", active.get("task_id", "current"))
    if elapsed_min >= planned:
        return (
            f"⏱️ SmartFocus: Focus session for '{task_title}' is past its planned "
            f"{planned} min (elapsed: {elapsed_min:.0f} min). "
            f"Consider stopping or extending."
        )
    return None


def _get_active_session_id() -> str | None:
    """Return the active session ID if any."""
    active = state.get_active_session()
    return active.get("id", "") if active else None


# ─── Active app tracking ──────────────────────────────

# Track the last detected app per session for switch detection
_last_active_app: dict[str, str] = {}


def _detect_active_app() -> str | None:
    """Detect the frontmost application name on macOS via osascript."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _is_work_app(app_name: str, work_tools: list[str]) -> bool:
    """Check if an app is a work tool using case-insensitive substring matching."""
    if not app_name:
        return False
    app_lower = app_name.lower()
    for tool in work_tools:
        if not tool:
            continue
        tool_lower = tool.lower()
        if tool_lower in app_lower or app_lower in tool_lower:
            return True
    return False


def _run_activity_tracking() -> None:
    """Detect the frontmost app and record it as activity for the active session.

    Called every poll cycle (30 sec). If the frontmost app matches a work tool,
    the time is counted as focused. Otherwise it's recorded as a distraction.
    Also detects app switches and records them.
    """
    if not _activity_available:
        return  # Preflight found osascript unavailable — skip silently
    try:
        active = state.get_active_session()
        if not active:
            _last_active_app.clear()
            return

        session_id = active.get("id", "")
        if not session_id:
            return

        app_name = _detect_active_app()
        if not app_name:
            return  # can't detect (non-macOS, accessibility denied)

        # Build the work tools list: session-specific + global setting + known work apps
        from config import WORK_APPS
        session_tools = active.get("work_tools", [])
        global_tools = state.get_setting("work_tools", [])
        all_tools = list(set(session_tools + global_tools + list(WORK_APPS)))

        is_related = _is_work_app(app_name, all_tools)

        # Record activity (duration = POLL_INTERVAL_SEC)
        import session as session_mod
        session_mod.record_activity(
            session_id, app_name, POLL_INTERVAL_SEC, is_related
        )

        # Detect and record app switch
        last_app = _last_active_app.get(session_id)
        if last_app and last_app != app_name:
            is_planned = _is_work_app(app_name, all_tools)
            session_mod.record_switch(
                session_id, last_app, app_name, is_planned
            )

        _last_active_app[session_id] = app_name

    except Exception as e:
        sys.stderr.write(f"[smartfocus] activity tracking failed: {e}\n")


# ─── Email scanning ───────────────────────────────────


def _run_email_scan() -> None:
    """Scan Thunderbird INBOX for new emails. Inject nudges for task emails."""
    if not _email_available:
        return  # Preflight found Thunderbird unavailable — skip silently
    try:
        import email_scanner

        # Get profile path from settings or auto-detect
        profile_path = state.get_setting("thunderbird_profile_path", "") or None

        result = email_scanner.scan_emails(
            profile_path=profile_path,
            state_dir=_state_dir(),
        )

        if result.get("error"):
            sys.stderr.write(f"[smartfocus] email scan error: {result['error']}\n")
            return

        new_emails = result.get("new_emails", [])
        task_emails = result.get("new_task_emails", [])

        if not new_emails:
            return

        # Create Task objects from emails with [task-XXX] tags
        # so they enter the common task list and get evaluated by the Eisenhower matrix
        tasks_imported = 0
        if task_emails:
            tasks_imported = email_scanner.create_tasks_from_emails(task_emails)

        # If session is active, store emails as session emails
        session_id = _get_active_session_id()
        if session_id:
            for email in new_emails:
                state.add_session_email(session_id, {
                    "subject": email.get("subject", ""),
                    "from": email.get("from", ""),
                    "date": email.get("date", ""),
                    "task_id": email.get("task_id"),
                    "has_task": email.get("has_task", False),
                })

        # Nudge about new task emails — filtered by priority during active session
        if task_emails:
            if session_id:
                # Active session — only nudge about emails whose priority exceeds
                # the current task's priority; defer the rest silently
                active = state.get_active_session()
                task_id = active.get("task_id", "") if active else ""
                current_priority = 0.5  # default if task not yet prioritized
                if task_id:
                    for t in state.get_tasks():
                        if t.get("id") == task_id:
                            current_priority = t.get("priority_score", 0.5)
                            break

                import notifications as notif_mod
                high_priority = []
                for email in task_emails:
                    notif = notif_mod.create_synthetic_notification({
                        "source": "email",
                        "title": email.get("subject", ""),
                        "body": email.get("from", ""),
                        "requires_action": True,
                        "is_important": False,
                        "has_deadline": False,
                    })
                    notif = notif_mod.evaluate_notification_priority(
                        notif, current_priority, True
                    )
                    if notif.action.value == "show_now":
                        high_priority.append(email)

                if high_priority:
                    task_list = ", ".join(
                        e.get("task_id", "?") for e in high_priority[:5]
                    )
                    _send_nudge(
                        f"📧 SmartFocus: {len(high_priority)} high-priority task email(s) "
                        f"from Thunderbird: [{task_list}]. "
                        f"{tasks_imported} task(s) imported to your task list."
                    )
                # else: all task emails deferred — priority below current task
            else:
                # No active session — nudge about all task emails
                task_list = ", ".join(
                    e.get("task_id", "?") for e in task_emails[:5]
                )
                count = len(task_emails)
                _send_nudge(
                    f"📧 SmartFocus: {count} new task email(s) from Thunderbird: "
                    f"[task-{task_list}]. "
                    f"{tasks_imported} task(s) imported to your task list."
                )

    except Exception as e:
        sys.stderr.write(f"[smartfocus] email scan failed: {e}\n")


# ─── Focus score monitoring ───────────────────────────


def _run_focus_check() -> None:
    """Check focus score of active session. Auto-stop if below threshold.

    On first drop below threshold: warn only.
    On second drop: auto-stop the session.
    """
    try:
        import session as session_mod

        active = state.get_active_session()
        if not active:
            return

        session_id = active.get("id", "")
        if not session_id:
            return

        # Skip focus check if no activity data has been recorded yet.
        # Without activities/switches, focused_time=0 → FTR=0 → score ≈ 0.38,
        # which would falsely trigger auto-stop on a session that simply has
        # no monitoring data yet.
        activities = active.get("activities", [])
        switches = active.get("switches", [])
        if not activities and not switches:
            return

        # Compute intermediate focus score (this appends a check to the session)
        check = session_mod.compute_intermediate_focus_score(session_id)
        if not check:
            return

        score = check.get("score", 1.0)
        threshold = state.get_setting("focus_score_threshold", FOCUS_SCORE_THRESHOLD)

        if score < threshold:
            # Reload session to get the updated focus_checks list
            updated = state.get_active_session()
            if not updated or updated.get("id") != session_id:
                return  # session was stopped by someone else
            focus_checks = updated.get("focus_checks", [])
            drops_below = sum(1 for c in focus_checks if c.get("score", 1.0) < threshold)

            if drops_below <= 1:
                # First drop — warn only
                _send_nudge(
                    f"⚠️ SmartFocus: Focus score dropped to {score:.2f} (threshold: {threshold}). "
                    f"Take a moment to refocus. The session will auto-stop on the next drop."
                )
                state.log_action("focus_drop_warning",
                                 f"Score {score:.3f} < {threshold}, drop #{drops_below} — warning sent")
            else:
                # Second drop — auto-stop
                result = session_mod.auto_stop_session("focus_score_below_threshold")
                if result:
                    _send_nudge(
                        f"🔴 SmartFocus: Focus session auto-stopped. "
                        f"Score: {score:.2f} (below threshold {threshold} for the 2nd time). "
                        f"Recommended next session: {result.get('next_session_duration_min', 25)} min."
                    )
                    state.log_action("focus_auto_stop",
                                     f"Score {score:.3f}, drop #{drops_below} — session auto-stopped")
                else:
                    sys.stderr.write(
                        f"[smartfocus] auto_stop_session returned None for {session_id}\n"
                    )
        else:
            # Score is fine — log quietly
            state.log_action("focus_check_ok", f"Score {score:.3f} >= {threshold}")

    except Exception as e:
        sys.stderr.write(f"[smartfocus] focus check failed: {e}\n")


# ─── Day summary (auto-trigger) ────────────────────────


def _run_day_summary_check() -> None:
    """Send a day summary nudge once per day if conditions are met.

    Conditions:
      - Current hour >= day_summary_hour (default 18:00)
      - At least 1 completed session today
      - Not already sent today (tracked via last_day_summary_date setting)
    """
    try:
        import report as report_mod

        now = datetime.now()
        trigger_hour = state.get_setting("day_summary_hour", 18)

        if now.hour < trigger_hour:
            return  # Too early in the day

        today_str = now.strftime("%Y-%m-%d")
        last_sent = state.get_setting("last_day_summary_date", "")
        if last_sent == today_str:
            return  # Already sent today

        today_sessions = state.get_today_sessions()
        completed = [
            s for s in today_sessions
            if s.get("status") in ("completed", "auto_stopped")
        ]
        if not completed:
            return  # No sessions to summarize

        report = report_mod.generate_report(now)

        lines = [
            f"📊 SmartFocus — Day Summary for {report['date']}",
            f"  Sessions: {report['focus_sessions']} | "
            f"Focused: {report['total_focused_minutes']} min | "
            f"Avg Score: {report['avg_focus_score']}",
            f"  Tasks: {report['completed_tasks']}/{report['planned_tasks']} done | "
            f"{report['incomplete_tasks']} incomplete | "
            f"{report['stuck_tasks']} stuck",
        ]
        if report.get("auto_stopped_sessions", 0):
            lines.append(
                f"  Auto-stopped: {report['auto_stopped_sessions']}"
            )
        if report.get("distraction_sources"):
            top_d = max(
                report["distraction_sources"],
                key=report["distraction_sources"].get,
            )
            lines.append(
                f"  Top distraction: {top_d} "
                f"({report['distraction_sources'][top_d]}x)"
            )
        lines.append(f"  Best focus hour: {report['best_focus_hour']}")

        next_rec = report.get("next_day_recommendation", {})
        if next_rec.get("items"):
            lines.append("  Tomorrow:")
            for item in next_rec["items"][:3]:
                lines.append(f"    • {item}")

        _send_nudge("\n".join(lines))
        state.set_setting("last_day_summary_date", today_str)
        state.log_action(
            "day_summary_sent",
            f"Summary for {today_str}: {report['focus_sessions']} sessions, "
            f"avg score {report['avg_focus_score']}",
        )

    except Exception as e:
        sys.stderr.write(f"[smartfocus] day summary check failed: {e}\n")


# ─── Main loop ────────────────────────────────────────


def main() -> None:
    """Main companion loop."""
    if not _state_dir():
        sys.stderr.write("[smartfocus] companion: OUROBOROS_SKILL_STATE_DIR not set\n")
        return
    state.init_state(_state_dir())
    if not _host_token():
        sys.stderr.write("[smartfocus] companion: HOST_SERVICE_TOKEN not set — nudges disabled\n")
    else:
        try:
            url = _host_url().rstrip("/") + "/identity"
            req = urllib.request.Request(url, headers={"X-Skill-Token": _host_token()}, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    sys.stderr.write(f"[smartfocus] Host Service probe: {resp.status}\n")
        except Exception as e:
            sys.stderr.write(f"[smartfocus] Host Service unreachable: {e}\n")

    # Preflight: Thunderbird profile availability
    global _email_available
    try:
        import email_scanner as _es
        _tb_profile = _es.find_thunderbird_profile()
        if not _tb_profile:
            sys.stderr.write(
                "[smartfocus] Thunderbird profile not found — email polling disabled\n"
            )
            _email_available = False
    except Exception as _e:
        sys.stderr.write(f"[smartfocus] Thunderbird preflight failed: {_e} — email polling disabled\n")
        _email_available = False

    # Preflight: osascript availability (macOS activity tracking)
    global _activity_available
    try:
        import shutil as _shutil
        if not _shutil.which("osascript"):
            sys.stderr.write(
                "[smartfocus] osascript not found — activity tracking disabled "
                "(non-macOS or missing Accessibility permissions)\n"
            )
            _activity_available = False
    except Exception:
        _activity_available = False

    last_nudge_ts: float = 0.0
    last_nudge_msg: str = ""
    last_email_scan_ts: float = 0.0
    last_focus_check_ts: float = 0.0
    focus_check_interval = state.get_setting("focus_check_interval_sec", FOCUS_CHECK_INTERVAL_SEC)

    while True:
        try:
            now_ts = time.time()

            # Active app tracking (every cycle — records activity + switches)
            _run_activity_tracking()

            # Session timer check (every cycle)
            nudge = _check_session()
            if nudge and nudge != last_nudge_msg:
                if now_ts - last_nudge_ts >= NUDGE_COOLDOWN_SEC:
                    _send_nudge(nudge)
                    last_nudge_ts = now_ts
                    last_nudge_msg = nudge
            else:
                last_nudge_msg = ""

            # Email scan (every EMAIL_SCAN_INTERVAL_SEC)
            if now_ts - last_email_scan_ts >= EMAIL_SCAN_INTERVAL_SEC:
                _run_email_scan()
                last_email_scan_ts = now_ts

            # Focus score check (every focus_check_interval)
            if now_ts - last_focus_check_ts >= focus_check_interval:
                _run_focus_check()
                last_focus_check_ts = now_ts

            # Day summary check (every cycle — cheap time comparison)
            _run_day_summary_check()

            time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            break
        except Exception as e:
            sys.stderr.write(f"[smartfocus] companion error: {e}\n")
            time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
