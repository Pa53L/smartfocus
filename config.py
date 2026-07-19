"""SmartFocus configuration constants — no filesystem side effects."""

FS_WEIGHTS = {
    "focused_time_ratio": 0.55,
    "switch_stability": 0.20,
    "recovery_rate": 0.15,
    "goal_progress": 0.10,
}

PRIO_WEIGHTS = {
    "deadline_proximity": 0.25,
    "explicit_urgency": 0.15,
    "task_influence": 0.10,
    "day_goal_link": 0.15,
    "non_execution_cost": 0.10,
    "repeat_reminders": 0.05,
    "complexity": 0.05,
    "available_time": 0.15,
}

SESSION_MIN_MINUTES = 15
SESSION_MAX_MINUTES = 50
SESSION_DEFAULT_MINUTES = 25

DISTRACTION_REMINDER_MINUTES = 5

# Focus monitoring during active session
FOCUS_CHECK_INTERVAL_SEC = 300  # 5 minutes between focus score checks
FOCUS_SCORE_THRESHOLD = 0.6     # auto-stop if score drops below this
FOCUS_SCORE_FIRST_DROP_WARN = True  # warn on first drop instead of stopping

# Task status when stopping a session
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_BREAK = "break"
TASK_STATUS_DEFERRED = "deferred"
TASK_STATUS_OPTIONS = [TASK_STATUS_COMPLETED, TASK_STATUS_BREAK, TASK_STATUS_DEFERRED]

DEFAULT_ALLOWED_APPS = ["CodeEditor", "Terminal", "Browser", "OpenIDE"]
DISTRACTION_APPS = {"Messenger", "SocialMedia", "Games", "YouTube"}
WORK_APPS = {"CodeEditor", "Terminal", "Browser", "IDE", "DocumentEditor", "OpenIDE"}
MEETING_APPS = {"Zoom", "Teams", "Calendar"}

# Default work tools — apps that count as focused work time.
# User can add/remove through the widget. Matching is case-insensitive substring.
DEFAULT_WORK_TOOLS = ["OpenIDE", "Terminal", "Browser", "CodeEditor"]

EMAIL_SCAN_INTERVAL_SEC = 180  # 3 minutes
DND_ENABLED_DEFAULT = True

DAY_SUMMARY_HOUR = 18  # send automatic day summary after this hour
DAY_SUMMARY_MIN_SESSIONS = 1  # minimum completed sessions to trigger summary

DEFAULT_SETTINGS = {
    "source_mode": "direct",
    "mcp_servers": [],
    "distraction_apps": list(DISTRACTION_APPS),
    "allowed_apps": DEFAULT_ALLOWED_APPS,
    "work_tools": list(DEFAULT_WORK_TOOLS),
    "session_default_minutes": SESSION_DEFAULT_MINUTES,
    "session_min_minutes": SESSION_MIN_MINUTES,
    "session_max_minutes": SESSION_MAX_MINUTES,
    "best_time_for_complex_tasks": "09:00",
    "notification_defer_minutes": 25,
    "reminder_delay_minutes": DISTRACTION_REMINDER_MINUTES,
    "vault_dir": "vault",
    "thunderbird_profile_path": "",  # auto-detect if empty
    "email_scan_interval_sec": EMAIL_SCAN_INTERVAL_SEC,
    "enable_dnd_on_session": DND_ENABLED_DEFAULT,
    "focus_score_threshold": FOCUS_SCORE_THRESHOLD,
    "focus_check_interval_sec": FOCUS_CHECK_INTERVAL_SEC,
    "day_summary_hour": DAY_SUMMARY_HOUR,
}

SOURCE_MODES = {"direct", "mcp", "hybrid"}
