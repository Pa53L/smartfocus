"""SmartFocus extension skill — PluginAPI registration.

Registers 14 agent-callable tools, HTTP routes for the widget,
a declarative UI tab (dashboard), a settings section, and a
companion process for proactive monitoring.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

# Ensure skill dir is on sys.path for local module imports
_SKILL_DIR = pathlib.Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

import state
import config
import models
import prioritize
import focus_score
import session as session_mod
import notifications
import normalize
import adapt
import knowledge
import report
import synthetic
import email_scanner


def _init_state_dir(api):
    sd = api.get_state_dir()
    state.init_state(sd)
    if not state.get_all_settings():
        state.set_settings(config.DEFAULT_SETTINGS)
    return sd


def register(api):
    _init_state_dir(api)

    # ─── Tools ───────────────────────────────────────────

    api.register_tool(
        "start_session",
        handler=_tool_start_session,
        description="Start a focus session for a task. Requires task_id, goal, expected_result. Optionally readiness (1-5), time_to_next_meeting (minutes), allowed_apps, and work_tools (tools needed for the task).",
        schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "goal": {"type": "string"},
                "expected_result": {"type": "string"},
                "readiness": {"type": "integer", "default": 3},
                "time_to_next_meeting": {"type": "integer", "default": 60},
                "allowed_apps": {"type": "array", "items": {"type": "string"}},
                "work_tools": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task_id", "goal", "expected_result"],
        },
        timeout_sec=30,
    )

    api.register_tool(
        "stop_session",
        handler=_tool_stop_session,
        description="Stop the active focus session. Optionally specify goal_achieved (bool), task_status (completed/break/deferred), and feedback (object).",
        schema={
            "type": "object",
            "properties": {
                "goal_achieved": {"type": "boolean", "default": False},
                "task_status": {"type": "string", "default": "",
                                "description": "completed, break, or deferred"},
                "feedback": {"type": "object"},
            },
        },
        timeout_sec=30,
    )

    api.register_tool(
        "get_status",
        handler=_tool_get_status,
        description="Get current SmartFocus status: active session, tasks, recent sessions, FocusScore.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=15,
    )

    api.register_tool(
        "add_task",
        handler=_tool_add_task,
        description="Add a task manually. Fields: title, importance (1-5), urgency (1-5), complexity (1-5), deadline (ISO), day_goal_link, source_ref.",
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "importance": {"type": "integer", "default": 3},
                "urgency": {"type": "integer", "default": 3},
                "complexity": {"type": "integer", "default": 3},
                "deadline": {"type": "string"},
                "day_goal_link": {"type": "string"},
                "source_ref": {"type": "string"},
            },
            "required": ["title"],
        },
        timeout_sec=15,
    )

    api.register_tool(
        "prioritize_tasks",
        handler=_tool_prioritize_tasks,
        description="Run prioritization on all pending tasks: Eisenhower quadrant, priority score, explanation, recommended start/duration.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=30,
    )

    api.register_tool(
        "get_top3",
        handler=_tool_get_top3,
        description="Get the TOP-3 priority tasks with explanations.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=15,
    )

    api.register_tool(
        "scan_sources",
        handler=_tool_scan_sources,
        description="Load synthetic demo datasets (successful_day, distracted_day, overloaded_day) into SmartFocus state. Normalizes, deduplicates, and processes notifications. Set source_mode in settings to configure future direct/MCP sources.",
        schema={
            "type": "object",
            "properties": {
                "dataset_name": {"type": "string"},
            },
        },
        timeout_sec=60,
    )

    api.register_tool(
        "get_focus_score",
        handler=_tool_get_focus_score,
        description="Get the FocusScore breakdown for the active or most recent session.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=15,
    )

    api.register_tool(
        "get_report",
        handler=_tool_get_report,
        description="Generate a daily report: completed/incomplete/stuck tasks, focus sessions, FocusScore, distraction sources, recommendation.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=30,
    )

    api.register_tool(
        "ask_ai",
        handler=_tool_ask_ai,
        description="Ask a question during a focus session. Saves Q&A as Markdown to the vault. Requires question; optionally provide answer (otherwise synthetic demo answer).",
        schema={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "answer": {"type": "string"},
            },
            "required": ["question"],
        },
        timeout_sec=30,
    )

    api.register_tool(
        "get_proposals",
        handler=_tool_get_proposals,
        description="Get adaptation proposals (observation, rationale, proposed change, status). Optionally filter by status (pending, accepted, rejected).",
        schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
            },
        },
        timeout_sec=15,
    )

    api.register_tool(
        "accept_proposal",
        handler=_tool_accept_proposal,
        description="Accept an adaptation proposal by ID. Applies the proposed change to settings.",
        schema={
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
            },
            "required": ["proposal_id"],
        },
        timeout_sec=15,
    )

    api.register_tool(
        "configure_sources",
        handler=_tool_configure_sources,
        description="Configure source settings: source_mode (direct/mcp/hybrid), mcp_servers list, distraction_apps list, allowed_apps list, session defaults.",
        schema={
            "type": "object",
            "properties": {
                "source_mode": {"type": "string"},
                "mcp_servers": {"type": "array", "items": {"type": "string"}},
                "distraction_apps": {"type": "array", "items": {"type": "string"}},
                "allowed_apps": {"type": "array", "items": {"type": "string"}},
                "session_default_minutes": {"type": "integer"},
                "reminder_delay_minutes": {"type": "integer"},
            },
        },
        timeout_sec=15,
    )

    api.register_tool(
        "propose_focus_slots",
        handler=_tool_propose_focus_slots,
        description="Propose focus work slots based on calendar events and past session FocusScore history. Pass calendar_events as list of {start, end, title} dicts.",
        schema={
            "type": "object",
            "properties": {
                "calendar_events": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of {start: ISO, end: ISO, title: str}",
                },
                "available_hours": {"type": "number", "default": 8.0},
            },
        },
        timeout_sec=15,
    )

    api.register_tool(
        "get_day_summary",
        handler=_tool_get_day_summary,
        description="Generate an end-of-day summary: overall focus score, task progress, session stats, and recommendations for the next day.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=30,
    )

    api.register_tool(
        "get_session_summary",
        handler=_tool_get_session_summary,
        description="Get summary of the last completed session: FocusScore, notification summary, next session recommendation, and emails received.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=15,
    )

    api.register_tool(
        "continue_task",
        handler=_tool_continue_task,
        description="Continue working on the task from the last session (if it was stopped with 'break' or 'deferred'). Starts a new session for the same task.",
        schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "expected_result": {"type": "string"},
                "readiness": {"type": "integer", "default": 3},
                "time_to_next_meeting": {"type": "integer", "default": 60},
            },
            "required": [],
        },
        timeout_sec=30,
    )

    api.register_tool(
        "reset_demo",
        handler=_tool_reset_demo,
        description="Reset all SmartFocus state (tasks, sessions, proposals, journal, vault) for demo replay.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=15,
    )

    api.register_tool(
        "record_activity",
        handler=_tool_record_activity,
        description="Record an activity entry (app name, duration) for the active focus session. Used to populate FocusScore.",
        schema={"type": "object", "properties": {
            "app_name": {"type": "string"},
            "duration_seconds": {"type": "number", "default": 30},
            "is_related": {"type": "boolean", "default": True},
        }, "required": ["app_name"]},
        timeout_sec=10,
    )

    api.register_tool(
        "record_switch",
        handler=_tool_record_switch,
        description="Record an app switch (from_app, to_app) during the active focus session.",
        schema={"type": "object", "properties": {
            "from_app": {"type": "string"},
            "to_app": {"type": "string"},
            "is_planned": {"type": "boolean", "default": False},
        }, "required": ["from_app", "to_app"]},
        timeout_sec=10,
    )

    api.register_tool(
        "process_notifications",
        handler=_tool_process_notifications,
        description="Process a batch of notifications through the SmartFocus filter (show_now vs defer) for the active session.",
        schema={"type": "object", "properties": {
            "items": {"type": "array", "items": {"type": "object"}},
        }, "required": ["items"]},
        timeout_sec=10,
    )

    api.register_tool(
        "scan_email",
        handler=_tool_scan_email,
        description="Manually trigger a Thunderbird INBOX scan for new emails. Extracts [task-XXX] from subjects. The companion also auto-scans every 3 minutes.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=60,
    )

    api.register_tool(
        "get_email_report",
        handler=_tool_get_email_report,
        description="Get emails received during the active or most recent focus session. Includes task-tagged emails and a summary.",
        schema={"type": "object", "properties": {}, "required": []},
        timeout_sec=15,
    )

    # ─── Routes ──────────────────────────────────────────

    api.register_route("status", handler=_route_status, methods=("GET",))
    api.register_route("matrix", handler=_route_matrix, methods=("GET",))
    api.register_route("start", handler=_route_start, methods=("POST",))
    api.register_route("stop", handler=_route_stop, methods=("POST",))
    api.register_route("scan", handler=_route_scan, methods=("POST",))
    api.register_route("config/save", handler=_route_config_save, methods=("POST",))
    api.register_route("config", handler=_route_config_get, methods=("GET",))
    api.register_route("top3", handler=_route_top3, methods=("GET",))
    api.register_route("proposals", handler=_route_proposals, methods=("GET",))
    api.register_route("report", handler=_route_report, methods=("GET",))
    api.register_route("email/scan", handler=_route_scan_email, methods=("POST",))
    api.register_route("email/report", handler=_route_email_report, methods=("GET",))
    api.register_route("slots", handler=_route_slots, methods=("GET",))
    api.register_route("day-summary", handler=_route_day_summary, methods=("GET",))
    api.register_route("session-summary", handler=_route_session_summary, methods=("GET",))
    api.register_route("reset", handler=_route_reset, methods=("POST",))
    api.register_route("tasks/select", handler=_route_tasks_select, methods=("GET",))
    api.register_route("work_tools", handler=_route_work_tools, methods=("GET",))
    api.register_route("work_tools/add", handler=_route_work_tools_add, methods=("POST",))
    api.register_route("work_tools/remove", handler=_route_work_tools_remove, methods=("POST",))

    # ─── Settings section ────────────────────────────────

    api.register_settings_section(
        "smartfocus",
        title="SmartFocus",
        schema={"components": [
            {"type": "form", "route": "config/save", "method": "POST", "fields": [
                {"name": "source_mode", "label": "Source Mode", "type": "text",
                 "placeholder": "direct, mcp, or hybrid"},
                {"name": "mcp_servers", "label": "MCP Servers (comma-separated)", "type": "text",
                 "placeholder": "http://localhost:3000/sse"},
                {"name": "distraction_apps", "label": "Distraction Apps (comma-separated)", "type": "text",
                 "placeholder": "Messenger, SocialMedia, YouTube"},
                {"name": "allowed_apps", "label": "Allowed Apps (comma-separated)", "type": "text",
                 "placeholder": "CodeEditor, Terminal, Browser"},
                {"name": "work_tools", "label": "Work Tools (comma-separated)", "type": "text",
                 "placeholder": "OpenIDE, Terminal, Browser"},
                {"name": "session_default_minutes", "label": "Default Session (min)", "type": "number",
                 "default": 25},
                {"name": "reminder_delay_minutes", "label": "Reminder Delay (min)", "type": "number",
                 "default": 5},
                {"name": "day_summary_hour", "label": "Day Summary Hour (24h)", "type": "number",
                 "default": 18},
                {"name": "thunderbird_profile_path", "label": "Thunderbird Profile Path (empty=auto)", "type": "text",
                 "placeholder": "/Users/you/Library/Thunderbird/Profiles/xxx.default-release"},
                {"name": "enable_dnd_on_session", "label": "Enable DND on Session Start", "type": "boolean",
                 "default": True},
            ]},
            {"type": "json", "source": "current_config"},
        ]},
    )

    # ─── UI tab (widget) ────────────────────────────────

    api.register_ui_tab(
        "sf_dashboard",
        "SmartFocus",
        icon="target",
        render={
            "kind": "declarative",
            "schema_version": 1,
            "span": 2,
            "components": [
                {
                    "type": "poll",
                    "route": "status",
                    "method": "GET",
                    "interval_ms": 10000,
                    "max_ticks": 100,
                    "auto_start": True,
                    "target": "sf_data",
                },
                {
                    "type": "kv",
                    "target": "sf_data",
                    "title": "Active Session",
                    "fields": [
                        {"label": "Status", "path": "session.status"},
                        {"label": "Task", "path": "session.task_title"},
                        {"label": "Goal", "path": "session.goal"},
                        {"label": "Elapsed (min)", "path": "session.elapsed_min"},
                        {"label": "Planned (min)", "path": "session.planned_min"},
                        {"label": "FocusScore", "path": "session.focus_score"},
                    ],
                },
                {
                    "type": "table",
                    "target": "sf_data",
                    "path": "top3",
                    "title": "TOP-3 Tasks",
                    "columns": [
                        {"label": "Task", "path": "title"},
                        {"label": "Source", "path": "source"},
                        {"label": "Q", "path": "quadrant"},
                        {"label": "Score", "path": "priority_score"},
                        {"label": "Why", "path": "priority_explanation"},
                    ],
                },
                {
                    "type": "poll",
                    "route": "matrix",
                    "method": "GET",
                    "interval_ms": 30000,
                    "max_ticks": 100,
                    "auto_start": True,
                    "target": "sf_matrix",
                },
                {
                    "type": "markdown",
                    "target": "sf_matrix",
                    "path": "matrix_markdown",
                },
                {
                    "type": "poll",
                    "route": "tasks/select",
                    "method": "GET",
                    "interval_ms": 15000,
                    "max_ticks": 100,
                    "auto_start": True,
                    "target": "sf_task_select",
                },
                {
                    "type": "form",
                    "route": "start",
                    "method": "POST",
                    "target": "start_result",
                    "visible_when": {"target": "sf_data", "path": "session.status", "not_equals": "active"},
                    "fields": [
                        {"name": "task_id", "label": "Select Task", "type": "select",
                         "options_target": "sf_task_select", "options_path": "options",
                         "required": True},
                        {"name": "goal", "label": "Session Goal", "type": "text"},
                        {"name": "expected_result", "label": "Expected Result", "type": "text"},
                        {"name": "readiness", "label": "Readiness (1-5)", "type": "number", "default": 3},
                    ],
                    "submit_label": "Start Session",
                },
                {
                    "type": "json",
                    "target": "start_result",
                    "label": "Start Result",
                    "visible_when": {"target": "sf_data", "path": "session.status", "not_equals": "active"},
                },
                {
                    "type": "action",
                    "route": "stop",
                    "method": "POST",
                    "label": "Stop Session",
                    "target": "stop_result",
                    "visible_when": {"target": "sf_data", "path": "session.status", "equals": "active"},
                },
                {
                    "type": "json",
                    "target": "stop_result",
                    "label": "Stop Result",
                    "visible_when": {"target": "sf_data", "path": "session.status", "equals": "active"},
                },
                {
                    "type": "action",
                    "route": "scan",
                    "method": "POST",
                    "label": "Scan Sources",
                    "target": "scan_result",
                },
                {
                    "type": "json",
                    "target": "scan_result",
                    "label": "Scan Result",
                },
                {
                    "type": "action",
                    "route": "email/scan",
                    "method": "POST",
                    "label": "Scan Email (Thunderbird)",
                    "target": "email_scan_result",
                },
                {
                    "type": "json",
                    "target": "email_scan_result",
                    "label": "Email Scan Result",
                },
                {
                    "type": "poll",
                    "route": "email/report",
                    "method": "GET",
                    "interval_ms": 30000,
                    "max_ticks": 100,
                    "auto_start": True,
                    "target": "sf_email_report",
                },
                {
                    "type": "kv",
                    "target": "sf_email_report",
                    "title": "Emails During Session",
                    "fields": [
                        {"label": "Total Emails", "path": "total_emails"},
                        {"label": "Task Emails", "path": "task_emails_count"},
                    ],
                },
                {
                    "type": "json",
                    "target": "sf_email_report",
                    "label": "Email Report Details",
                    "path": "all_emails",
                },
                {
                    "type": "poll",
                    "route": "work_tools",
                    "method": "GET",
                    "interval_ms": 30000,
                    "max_ticks": 100,
                    "auto_start": True,
                    "target": "sf_work_tools",
                },
                {
                    "type": "kv",
                    "target": "sf_work_tools",
                    "title": "Work Tools (count as focused time)",
                    "fields": [
                        {"label": "Tools", "path": "work_tools_str"},
                        {"label": "Count", "path": "count"},
                    ],
                },
                {
                    "type": "form",
                    "route": "work_tools/add",
                    "method": "POST",
                    "target": "wt_add_result",
                    "fields": [
                        {"name": "app_name", "label": "App Name", "type": "text",
                         "placeholder": "e.g. OpenIDE, Xcode, Safari",
                         "required": True},
                    ],
                    "submit_label": "Add Work Tool",
                },
                {
                    "type": "json",
                    "target": "wt_add_result",
                    "label": "Add Result",
                },
                {
                    "type": "form",
                    "route": "work_tools/remove",
                    "method": "POST",
                    "target": "wt_remove_result",
                    "fields": [
                        {"name": "app_name", "label": "App Name to Remove", "type": "text",
                         "required": True},
                    ],
                    "submit_label": "Remove Work Tool",
                },
                {
                    "type": "json",
                    "target": "wt_remove_result",
                    "label": "Remove Result",
                },
            ],
        },
    )

    # ─── Companion process ───────────────────────────────

    api.register_companion_process("monitor")

    api.on_unload(_cleanup)


# ─── Tool handlers ──────────────────────────────────────


def _tool_start_session(ctx, task_id: str = "", goal: str = "",
                        expected_result: str = "", readiness: int = 3,
                        time_to_next_meeting: int = 60, allowed_apps: list | None = None,
                        work_tools: list | None = None) -> str:
    # Guard: reject empty task_id or goal (prevents ghost sessions)
    if not task_id or not task_id.strip() or not goal or not goal.strip():
        return json.dumps({"error": "task_id and goal are required"}, ensure_ascii=False)
    # Guard: refuse to start if a session is already active
    active = state.get_active_session()
    if active:
        return json.dumps({"error": "A focus session is already active. Stop it first.",
                           "active_session_id": active.get("id", "")}, ensure_ascii=False)
    tasks = state.get_tasks()
    task_title = ""
    task_priority = 0.0
    for t in tasks:
        if t.get("id") == task_id:
            task_title = t.get("title", "")
            task_priority = t.get("priority_score", 0.0)
            break
    result = session_mod.start_session(
        task_id=task_id, goal=goal, expected_result=expected_result,
        allowed_apps=allowed_apps, readiness=readiness,
        time_to_next_meeting=time_to_next_meeting,
        task_title=task_title,
        work_tools=work_tools,
    )
    # Store task priority on the session for notification comparison
    if task_priority > 0 and "id" in result:
        state.modify_session(result["id"], lambda s: s.update({"task_priority": task_priority}))
    return json.dumps(result, ensure_ascii=False)


def _tool_stop_session(ctx, goal_achieved: bool = False, task_status: str = "",
                       feedback: dict | None = None) -> str:
    result = session_mod.stop_session(
        goal_achieved=goal_achieved,
        feedback=feedback,
        task_status=task_status,
    )
    if result is None:
        return json.dumps({"error": "No active focus session"})
    # Trigger adaptation analysis after session completion
    adaptation_warning = None
    try:
        adapt.analyze_sessions_and_propose(state.get_sessions())
    except Exception as e:
        state.log_action("adaptation_error", str(e))
        adaptation_warning = str(e)
    result_dict = dict(result)
    if adaptation_warning:
        result_dict["adaptation_warning"] = adaptation_warning
    return json.dumps(result_dict, ensure_ascii=False)


def _tool_get_status(ctx) -> str:
    tasks = state.get_tasks()
    active = state.get_active_session()
    sessions = state.get_sessions()
    completed = [s for s in sessions if s.get("status") == "completed"]
    return json.dumps({
        "active_session": active,
        "task_count": len(tasks),
        "pending_tasks": len([t for t in tasks if t.get("status") == "pending"]),
        "completed_sessions": len(completed),
        "recent_sessions": completed[-5:] if completed else [],
        "settings": state.get_all_settings(),
    }, ensure_ascii=False)


def _tool_add_task(ctx, title: str = "", importance: int = 3, urgency: int = 3,
                   complexity: int = 3, deadline: str = "",
                   day_goal_link: str = "", source_ref: str = "") -> str:
    from datetime import datetime
    t = models.Task(
        title=title, importance=importance, urgency=urgency, complexity=complexity,
        day_goal_link=day_goal_link, source_ref=source_ref,
        source=models.TaskSource.MANUAL,
    )
    if deadline:
        try:
            parsed = datetime.fromisoformat(deadline)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            t.deadline = parsed
        except ValueError:
            return json.dumps({"error": f"Invalid deadline format: {deadline}. Use ISO format like 2026-07-15T18:00"}, ensure_ascii=False)
    t.compute_quadrant()
    state.append_task(t.to_dict())
    state.log_action("add_task", f"Added: {title}")
    return json.dumps(t.to_dict(), ensure_ascii=False)


def _tool_prioritize_tasks(ctx) -> str:
    task_dicts = state.get_tasks()
    tasks = [models.Task.from_dict(t) for t in task_dicts]
    prioritized = prioritize.prioritize(tasks)
    result = [t.to_dict() for t in prioritized]
    state.save_tasks(result)
    # Cap output to prevent unbounded growth
    capped = result[:50]
    return json.dumps({
        "tasks": capped,
        "total_count": len(result),
        "shown_count": len(capped),
        "omitted_count": max(0, len(result) - len(capped)),
    }, ensure_ascii=False)


def _tool_get_top3(ctx) -> str:
    task_dicts = state.get_tasks()
    tasks = [models.Task.from_dict(t) for t in task_dicts]
    if not tasks:
        return json.dumps([])
    prioritized = prioritize.prioritize(tasks)
    top3 = prioritize.get_top3(prioritized)
    return json.dumps([t.to_dict() for t in top3], ensure_ascii=False)


def _tool_scan_sources(ctx, dataset_name: str = "") -> str:
    source_mode = state.get_setting("source_mode", "direct")
    if not dataset_name:
        dataset_name = "successful_day"
    ds = synthetic.load_dataset(dataset_name)
    if not ds:
        return json.dumps({"error": f"Unknown dataset: {dataset_name}"})

    raw_data = {
        "tasks": ds.get("tasks", []),
        "emails": ds.get("emails", []),
        "messages": ds.get("messages", []),
    }
    normalize.normalize_all(raw_data)

    existing_tasks = state.get_tasks()
    existing_ids = {t.get("id", "") for t in existing_tasks}
    existing_refs = {t.get("source_ref", "") for t in existing_tasks if t.get("source_ref")}
    new_count = 0
    for t_dict in raw_data["tasks"]:
        tid = t_dict.get("id", "")
        tref = t_dict.get("source_ref", "")
        if tid and tid in existing_ids:
            continue
        if tref and tref in existing_refs:
            continue
        existing_tasks.append(t_dict)
        new_count += 1
    state.save_tasks(existing_tasks)

    # Process notifications from dataset through the filter
    active_session = state.get_active_session()
    session_active = active_session is not None
    session_id = active_session.get("id", "") if active_session else ""
    ds_notifications = ds.get("notifications", [])
    if ds_notifications:
        notif_objs = [notifications.create_synthetic_notification(n) for n in ds_notifications]
        processed = notifications.process_notification_batch(notif_objs, session_active, session_id)
        urgent = notifications.get_urgent_notifications(processed)
        deferred = notifications.get_deferred_notifications(processed)
        notif_summary = {"urgent": len(urgent), "deferred": len(deferred)}
    else:
        notif_summary = {"urgent": 0, "deferred": 0}

    state.log_action("scan_sources", f"Scanned ({source_mode}): {new_count} new tasks, "
                     f"{len(raw_data['emails'])} emails, {len(raw_data['messages'])} messages, "
                     f"notifications: {notif_summary}")
    return json.dumps({
        "source_mode": source_mode,
        "dataset": dataset_name,
        "imported_tasks": new_count,
        "skipped_duplicates": len(raw_data["tasks"]) - new_count,
        "imported_emails": len(raw_data["emails"]),
        "imported_messages": len(raw_data["messages"]),
        "notifications": notif_summary,
    }, ensure_ascii=False)


def _tool_get_focus_score(ctx) -> str:
    sessions = state.get_sessions()
    active = state.get_active_session()
    target = active or (sessions[-1] if sessions else None)
    if not target:
        return json.dumps({"error": "No sessions found"})
    if active:
        s = models.FocusSession.from_dict(active)
        breakdown = focus_score.compute_focus_score(s)
        return json.dumps(breakdown.to_dict(), ensure_ascii=False)
    return json.dumps({
        "focus_score": target.get("focus_score", 0),
        "breakdown": target.get("focus_score_breakdown", {}),
    }, ensure_ascii=False)


def _tool_get_report(ctx) -> str:
    rep = report.generate_report()
    return json.dumps(rep, ensure_ascii=False)


def _tool_ask_ai(ctx, question: str = "", answer: str = "") -> str:
    active = state.get_active_session()
    session_id = active.get("id", "") if active else ""
    task_id = active.get("task_id", "") if active else ""
    task_title = active.get("task_title", "") if active else ""
    if not answer:
        answer = knowledge.generate_synthetic_answer(question, task_title)
    entry = knowledge.create_qa_entry(
        session_id=session_id, task_id=task_id,
        question=question, answer=answer,
    )
    return json.dumps(entry, ensure_ascii=False)


def _tool_get_proposals(ctx, status: str = "") -> str:
    proposals = adapt.get_proposals(status if status else None)
    capped = proposals[:50]
    return json.dumps({
        "proposals": capped,
        "total_count": len(proposals),
        "shown_count": len(capped),
        "omitted_count": max(0, len(proposals) - len(capped)),
    }, ensure_ascii=False)


def _tool_accept_proposal(ctx, proposal_id: str = "") -> str:
    result = adapt.accept_proposal(proposal_id)
    if result is None:
        return json.dumps({"error": "Proposal not found or not in accepted state"})
    return json.dumps(result, ensure_ascii=False)


def _tool_configure_sources(ctx, source_mode: str = "", mcp_servers: list | None = None,
                             distraction_apps: list | None = None,
                             allowed_apps: list | None = None,
                             session_default_minutes: int = 0,
                             reminder_delay_minutes: int = 0,
                             day_summary_hour: int = 0) -> str:
    updates = {}
    if source_mode and source_mode in config.SOURCE_MODES:
        updates["source_mode"] = source_mode
    if mcp_servers is not None:
        updates["mcp_servers"] = mcp_servers
    if distraction_apps is not None:
        updates["distraction_apps"] = distraction_apps
    if allowed_apps is not None:
        updates["allowed_apps"] = allowed_apps
    if session_default_minutes > 0:
        updates["session_default_minutes"] = session_default_minutes
    if reminder_delay_minutes > 0:
        updates["reminder_delay_minutes"] = reminder_delay_minutes
    if day_summary_hour > 0:
        updates["day_summary_hour"] = day_summary_hour
    if updates:
        state.set_settings(updates)
    return json.dumps(state.get_all_settings(), ensure_ascii=False)


def _tool_reset_demo(ctx) -> str:
    state.reset_state()
    state.set_settings(config.DEFAULT_SETTINGS)
    state.log_action("reset_demo", "All state reset")
    return json.dumps({"status": "reset", "message": "All state cleared. Ready for demo replay."})


def _tool_propose_focus_slots(ctx, calendar_events: list | None = None,
                              available_hours: float = 8.0) -> str:
    result = session_mod.propose_focus_slots(
        available_hours=available_hours,
        calendar_events=calendar_events,
    )
    return json.dumps(result, ensure_ascii=False)


def _tool_get_day_summary(ctx) -> str:
    """End-of-day summary: overall focus, task progress, next-day recommendations."""
    rep = report.generate_report()
    today_sessions = state.get_today_sessions()
    completed = [s for s in today_sessions
                 if s.get("status") in ("completed", "auto_stopped")]
    scores = [s.get("focus_score", 0) for s in completed if s.get("focus_score", 0) > 0]
    total_focused = sum(s.get("focused_time", 0) for s in completed)

    summary = {
        "date": rep.get("date", ""),
        "sessions_count": len(completed),
        "total_focused_minutes": round(total_focused, 1),
        "avg_focus_score": round(sum(scores) / len(scores), 3) if scores else 0,
        "focus_scores": [round(s, 3) for s in scores],
        "auto_stopped_count": rep.get("auto_stopped_sessions", 0),
        "completed_tasks": rep.get("completed_tasks", 0),
        "incomplete_tasks": rep.get("incomplete_tasks", 0),
        "carried_over_tasks": rep.get("carried_over_tasks", 0),
        "best_focus_hour": rep.get("best_focus_hour", "09:00"),
        "distraction_sources": rep.get("distraction_sources", {}),
        "next_day_recommendation": rep.get("next_day_recommendation", {}),
        "recommendation": rep.get("recommendation", ""),
    }
    state.log_action("day_summary", f"Sessions: {len(completed)}, Avg score: {summary['avg_focus_score']}")
    return json.dumps(summary, ensure_ascii=False)


def _tool_get_session_summary(ctx) -> str:
    """Get summary of the last completed session."""
    last = state.get_last_completed_session()
    if not last:
        return json.dumps({"error": "No completed sessions found"})
    return json.dumps({
        "session_id": last.get("id", ""),
        "task_title": last.get("task_title", ""),
        "task_status": last.get("task_status", ""),
        "focus_score": round(last.get("focus_score", 0), 3),
        "focus_score_breakdown": last.get("focus_score_breakdown", {}),
        "planned_duration": last.get("planned_duration", 0),
        "actual_duration": last.get("actual_duration", 0),
        "next_session_duration_min": last.get("next_session_duration_min", 0),
        "notification_summary": last.get("notification_summary", {}),
        "emails_count": last.get("emails_count", 0),
        "auto_stopped": last.get("status") == "auto_stopped",
    }, ensure_ascii=False)


def _tool_continue_task(ctx, goal: str = "", expected_result: str = "",
                        readiness: int = 3, time_to_next_meeting: int = 60) -> str:
    """Continue working on the task from the last session."""
    last = state.get_last_completed_session()
    if not last:
        return json.dumps({"error": "No previous session found to continue"})
    task_id = last.get("task_id", "")
    task_title = last.get("task_title", "")
    if not task_id:
        return json.dumps({"error": "Last session has no task_id"})
    # Use previous goal/expected_result if not provided
    if not goal:
        goal = last.get("goal", "Continue work")
    if not expected_result:
        expected_result = last.get("expected_result", "")
    # Use recommended duration from last session
    recommended = last.get("next_session_duration_min", 0) or None
    result = session_mod.start_session(
        task_id=task_id, goal=goal, expected_result=expected_result,
        readiness=readiness, time_to_next_meeting=time_to_next_meeting,
        task_title=task_title,
        recommended_duration=recommended,
        work_tools=last.get("work_tools", []),
    )
    return json.dumps(result, ensure_ascii=False)


def _tool_record_activity(ctx, app_name: str = "", duration_seconds: float = 30,
                          is_related: bool = True) -> str:
    active = state.get_active_session()
    if not active:
        return json.dumps({"error": "No active focus session"})
    result = session_mod.record_activity(active["id"], app_name, duration_seconds, is_related)
    if result is None:
        return json.dumps({"error": "Session not found"})
    return json.dumps(result, ensure_ascii=False)


def _tool_record_switch(ctx, from_app: str = "", to_app: str = "",
                        is_planned: bool = False) -> str:
    active = state.get_active_session()
    if not active:
        return json.dumps({"error": "No active focus session"})
    result = session_mod.record_switch(active["id"], from_app, to_app, is_planned)
    if result is None:
        return json.dumps({"error": "Session not found"})
    return json.dumps(result, ensure_ascii=False)


def _tool_process_notifications(ctx, items: list | None = None) -> str:
    active = state.get_active_session()
    notif_objs = []
    for n in (items or []):
        notif_objs.append(notifications.create_synthetic_notification(n))
    session_active = active is not None
    session_id = active.get("id", "") if active else ""
    processed = notifications.process_notification_batch(notif_objs, session_active, session_id)
    urgent = notifications.get_urgent_notifications(processed)
    deferred = notifications.get_deferred_notifications(processed)
    return json.dumps({
        "urgent": [n.to_dict() for n in urgent],
        "deferred": [n.to_dict() for n in deferred],
        "total": len(processed),
    }, ensure_ascii=False)


def _tool_scan_email(ctx) -> str:
    """Manually trigger a Thunderbird email scan."""
    profile_path = state.get_setting("thunderbird_profile_path", "") or None
    result = email_scanner.scan_emails(
        profile_path=profile_path,
        state_dir=state.get_state_dir(),
    )
    new_emails = result.get("new_emails", [])
    task_emails = result.get("new_task_emails", [])

    # Create Task objects from emails with [task-XXX] tags
    # so they enter the common task list and get evaluated by the Eisenhower matrix
    new_tasks_from_email = 0
    if task_emails:
        new_tasks_from_email = email_scanner.create_tasks_from_emails(task_emails)

    # If session active, store emails
    active = state.get_active_session()
    if active and new_emails:
        for email in new_emails:
            state.add_session_email(active["id"], {
                "subject": email.get("subject", ""),
                "from": email.get("from", ""),
                "date": email.get("date", ""),
                "task_id": email.get("task_id"),
                "has_task": email.get("has_task", False),
            })

    state.log_action("scan_email",
                     f"New: {len(new_emails)}, Task emails: {len(task_emails)}, "
                     f"Tasks imported: {new_tasks_from_email}")
    return json.dumps({
        "new_emails_count": len(new_emails),
        "task_emails_count": len(task_emails),
        "tasks_imported": new_tasks_from_email,
        "task_emails": task_emails[:10],
        "total_seen": result.get("total_seen", 0),
        "error": result.get("error"),
    }, ensure_ascii=False)


def _tool_get_email_report(ctx) -> str:
    """Get emails received during the active or most recent session."""
    active = state.get_active_session()
    sessions = state.get_sessions()
    if active:
        session_id = active["id"]
        session_desc = "active session"
    elif sessions:
        session_id = sessions[-1].get("id", "")
        session_desc = "most recent session"
    else:
        return json.dumps({"error": "No sessions found"})

    emails = state.get_session_emails(session_id)
    task_emails = [e for e in emails if e.get("has_task")]
    return json.dumps({
        "session_id": session_id,
        "session": session_desc,
        "total_emails": len(emails),
        "task_emails_count": len(task_emails),
        "task_emails": task_emails[:50],
        "all_emails": emails[-20:] if len(emails) > 20 else emails,
        "omitted_task_emails": max(0, len(task_emails) - 50),
    }, ensure_ascii=False)


# ─── Route handlers ─────────────────────────────────────


async def _parse_body(request) -> tuple[dict, str | None]:
    """Parse request JSON body. Returns (data, error_str)."""
    if request is None:
        return {}, None
    if isinstance(request, dict):
        return request, None
    if hasattr(request, "json"):
        try:
            return await request.json(), None
        except Exception:
            return {}, "invalid JSON body"
    return {}, None


def _route_status(request=None) -> dict:
    tasks = state.get_tasks()
    active = state.get_active_session()
    sessions = state.get_sessions()
    completed = [s for s in sessions if s.get("status") == "completed"]

    session_data = {}
    if active:
        elapsed = session_mod.get_session_elapsed_minutes(active)
        planned = active.get("planned_duration", 25)
        session_data = {
            "status": "active",
            "task_title": active.get("task_title", ""),
            "goal": active.get("goal", ""),
            "elapsed_min": round(elapsed, 1),
            "planned_min": planned,
            "focus_score": round(active.get("focus_score", 0), 3),
        }
    else:
        session_data = {"status": "inactive"}

    top3_raw = []
    if tasks:
        task_objs = [models.Task.from_dict(t) for t in tasks]
        prioritized = prioritize.prioritize(task_objs)
        top3 = prioritize.get_top3(prioritized)
        top3_raw = [t.to_dict() for t in top3]

    return {
        "session": session_data,
        "top3": top3_raw,
        "task_count": len(tasks),
        "completed_sessions": len(completed),
    }


def _route_matrix(request=None) -> dict:
    tasks = state.get_tasks()
    task_objs = [models.Task.from_dict(t) for t in tasks]
    # Cap tasks shown in matrix to prevent unbounded output
    if len(task_objs) > 50:
        task_objs = task_objs[:50]
    if task_objs:
        prioritize.prioritize(task_objs)
    matrix = prioritize.get_eisenhower_matrix(task_objs)
    md = prioritize.matrix_to_markdown(matrix)
    return {"matrix_markdown": md, "total_tasks": len(tasks), "shown_tasks": len(task_objs)}


async def _route_start(request=None) -> dict:
    data, parse_err = await _parse_body(request)
    if parse_err:
        return {"error": parse_err}

    task_id = str(data.get("task_id", ""))
    goal = str(data.get("goal", ""))
    expected_result = str(data.get("expected_result", ""))
    try:
        readiness = int(data.get("readiness", 3))
    except (ValueError, TypeError):
        readiness = 3
    if not task_id or not goal:
        return {"error": "task_id and goal are required"}

    tasks = state.get_tasks()
    task_title = ""
    for t in tasks:
        if t.get("id") == task_id:
            task_title = t.get("title", "")
            break
    # Pass global work_tools setting so companion can track focused time
    work_tools = state.get_setting("work_tools", [])
    result = session_mod.start_session(
        task_id=task_id, goal=goal, expected_result=expected_result,
        readiness=readiness, task_title=task_title,
        work_tools=work_tools,
    )
    return result


async def _route_stop(request=None) -> dict:
    data, parse_err = await _parse_body(request)
    if parse_err:
        return {"error": parse_err}
    goal_achieved = bool(data.get("goal_achieved", False))
    task_status = str(data.get("task_status", ""))
    result = session_mod.stop_session(
        goal_achieved=goal_achieved,
        task_status=task_status,
    )
    if result is None:
        return {"error": "No active session"}
    return result


async def _route_scan(request=None) -> dict:
    data, parse_err = await _parse_body(request)
    if parse_err:
        return {"error": parse_err}
    dataset_name = data.get("dataset_name", "successful_day")
    result = json.loads(_tool_scan_sources(None, dataset_name=dataset_name))
    return result


async def _route_config_save(request=None) -> dict:
    data, parse_err = await _parse_body(request)
    if parse_err:
        return {"error": parse_err}
    updates = {}
    for key in ["source_mode", "mcp_servers", "distraction_apps", "allowed_apps",
                "work_tools", "thunderbird_profile_path", "enable_dnd_on_session"]:
        val = data.get(key, "")
        if not val and key != "enable_dnd_on_session":
            continue
        if key in ("mcp_servers", "distraction_apps", "allowed_apps", "work_tools"):
            updates[key] = [s.strip() for s in str(val).split(",") if s.strip()]
        elif key == "enable_dnd_on_session":
            if isinstance(val, bool):
                updates[key] = val
            elif isinstance(val, str) and val.lower().strip() in ("true", "1", "yes", "false", "0", "no"):
                updates[key] = val.lower().strip() in ("true", "1", "yes")
        else:
            updates[key] = str(val).strip()
    if data.get("session_default_minutes"):
        try:
            updates["session_default_minutes"] = int(data["session_default_minutes"])
        except (ValueError, TypeError):
            pass
    if data.get("reminder_delay_minutes"):
        try:
            updates["reminder_delay_minutes"] = int(data["reminder_delay_minutes"])
        except (ValueError, TypeError):
            pass
    if data.get("day_summary_hour"):
        try:
            updates["day_summary_hour"] = int(data["day_summary_hour"])
        except (ValueError, TypeError):
            pass
    if updates:
        state.set_settings(updates)
    return {"status": "saved", "settings": state.get_all_settings()}


def _route_config_get(request=None) -> dict:
    return {"current_config": state.get_all_settings()}


def _route_top3(request=None) -> dict:
    return json.loads(_tool_get_top3(None))


def _route_proposals(request=None) -> dict:
    proposals = adapt.get_proposals()
    capped = proposals[:50]
    return {"proposals": capped, "total_count": len(proposals), "shown_count": len(capped)}


def _route_report(request=None) -> dict:
    return report.generate_report()


async def _route_scan_email(request=None) -> dict:
    return json.loads(_tool_scan_email(None))


def _route_email_report(request=None) -> dict:
    return json.loads(_tool_get_email_report(None))


def _route_slots(request=None) -> dict:
    return json.loads(_tool_propose_focus_slots(None))


def _route_day_summary(request=None) -> dict:
    return json.loads(_tool_get_day_summary(None))


def _route_session_summary(request=None) -> dict:
    return json.loads(_tool_get_session_summary(None))


async def _route_reset(request=None) -> dict:
    """Reset all state and reload default settings."""
    state.reset_state()
    state.set_settings(config.DEFAULT_SETTINGS)
    state.log_action("reset_demo", "All state reset via API route")
    return {"status": "reset", "message": "All state cleared. Ready for demo replay."}


def _route_tasks_select(request=None) -> dict:
    """Return prioritized tasks as select options for the dropdown, sorted by Eisenhower score."""
    task_dicts = state.get_tasks()
    if not task_dicts:
        return {"options": []}
    task_objs = [models.Task.from_dict(t) for t in task_dicts]
    prioritized = prioritize.prioritize(task_objs)
    options = []
    for t in prioritized:
        q = t.quadrant or ""
        score = round(t.priority_score, 2) if t.priority_score else 0
        label = f"{t.title}  (Q{q}, {score})"
        options.append({"value": t.id, "label": label})
    return {"options": options, "total_tasks": len(prioritized)}


def _route_work_tools(request=None) -> dict:
    """Return current work tools list for the widget."""
    tools = state.get_setting("work_tools", list(config.DEFAULT_WORK_TOOLS))
    return {
        "work_tools": tools,
        "work_tools_str": ", ".join(tools) if tools else "(none)",
        "count": len(tools),
    }


async def _route_work_tools_add(request=None) -> dict:
    """Add a work tool to the settings."""
    data, parse_err = await _parse_body(request)
    if parse_err:
        return {"error": parse_err}
    app_name = str(data.get("app_name", "")).strip()
    if not app_name:
        return {"error": "app_name is required"}
    tools = state.get_setting("work_tools", list(config.DEFAULT_WORK_TOOLS))
    if app_name not in tools:
        tools.append(app_name)
        state.set_setting("work_tools", tools)
        state.log_action("work_tool_added", app_name)
    return {"status": "added", "app_name": app_name, "work_tools": tools}


async def _route_work_tools_remove(request=None) -> dict:
    """Remove a work tool from the settings."""
    data, parse_err = await _parse_body(request)
    if parse_err:
        return {"error": parse_err}
    app_name = str(data.get("app_name", "")).strip()
    if not app_name:
        return {"error": "app_name is required"}
    tools = state.get_setting("work_tools", list(config.DEFAULT_WORK_TOOLS))
    if app_name in tools:
        tools.remove(app_name)
        state.set_setting("work_tools", tools)
        state.log_action("work_tool_removed", app_name)
    return {"status": "removed", "app_name": app_name, "work_tools": tools}


def _cleanup():
    try:
        state.log_action("unload", "SmartFocus extension unloaded")
    except Exception:
        pass
    # Best-effort DND restore if a session is still active on unload
    try:
        active = state.get_active_session()
        if active and state.get_setting("enable_dnd_on_session", True):
            try:
                import dnd
                dnd.disable_dnd()
            except Exception:
                pass
    except Exception:
        pass
    # Remove skill dir from sys.path to avoid polluting other extensions
    global _SKILL_DIR
    try:
        sp = str(_SKILL_DIR)
        while sp in sys.path:
            sys.path.remove(sp)
        # Remove smartfocus bare modules from sys.modules cache
        for mod_name in ["config", "state", "models", "prioritize", "focus_score",
                         "session", "notifications", "normalize", "adapt",
                         "knowledge", "report", "synthetic", "email_scanner", "dnd"]:
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "__file__") and mod.__file__ and sp in mod.__file__:
                del sys.modules[mod_name]
    except Exception:
        pass
