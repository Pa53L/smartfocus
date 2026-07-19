---
name: smartfocus
description: Proactive focus-session agent — task prioritization, Eisenhower matrix, FocusScore, distraction nudges, adaptive recommendations, Thunderbird email polling, Do Not Disturb toggle, periodic focus monitoring with auto-stop, calendar-aware slot proposals, session continuation, end-of-day summary
version: 0.1.0
type: extension
runtime: python3
entry: plugin.py
permissions: [tool, route, widget, companion_process, inject_chat, net, fs, subprocess]
env_from_settings: []
when_to_use: User wants to start/stop focus sessions, prioritize tasks, track FocusScore, get distraction nudges, scan Thunderbird emails for tasks, get email reports during sessions, propose focus time slots based on calendar, get day/session summaries, continue a task, or stop with task status (completed/break/deferred).
timeout_sec: 60
companion_processes:
  - name: monitor
    command: ["python3", "companion.py"]
    runtime: python3
    description: Periodic session timer check, distraction nudge, Thunderbird email polling every 3 minutes, and focus score monitoring every 5 minutes with auto-stop below threshold.
ui_tab:
  tab_id: sf_dashboard
  title: SmartFocus
  icon: target
  render:
    kind: declarative
    schema_version: 1
    components:
      - type: poll
        route: status
        method: GET
        interval_sec: 10
        target: sf_data
      - type: kv
        target: sf_data.session
        title: Active Session
        fields:
          - label: Status
            path: status
          - label: Task
            path: task_title
          - label: Goal
            path: goal
          - label: Elapsed (min)
            path: elapsed_min
          - label: Planned (min)
            path: planned_min
          - label: FocusScore
            path: focus_score
      - type: table
        target: sf_data.top3
        title: TOP-3 Tasks
        columns:
          - label: Task
            path: title
          - label: Q
            path: quadrant
          - label: Score
            path: priority_score
          - label: Why
            path: priority_explanation
      - type: poll
        route: matrix
        method: GET
        interval_sec: 30
        target: sf_matrix
      - type: markdown
        target: sf_matrix
        source: matrix_markdown
      - type: form
        route: start
        method: POST
        target: start_result
        visible_when:
          target: sf_data
          path: session.status
          not_equals: active
        fields:
          - name: task_id
            label: Task ID
            type: text
          - name: goal
            label: Session Goal
            type: text
          - name: expected_result
            label: Expected Result
            type: text
          - name: readiness
            label: Readiness (1-5)
            type: number
            default: 3
        submit_label: Start Session
      - type: json
        target: start_result
        label: Start Result
        visible_when:
          target: sf_data
          path: session.status
          not_equals: active
      - type: action
        route: stop
        method: POST
        label: Stop Session
        target: stop_result
        visible_when:
          target: sf_data
          path: session.status
          equals: active
      - type: json
        target: stop_result
        label: Stop Result
        visible_when:
          target: sf_data
          path: session.status
          equals: active
      - type: action
        route: scan
        method: POST
        label: Scan Sources
        target: scan_result
      - type: json
        target: scan_result
        label: Scan Result
      - type: action
        route: email/scan
        method: POST
        label: Scan Email (Thunderbird)
        target: email_scan_result
      - type: json
        target: email_scan_result
        label: Email Scan Result
      - type: poll
        route: email/report
        method: GET
        interval_sec: 30
        target: sf_email_report
      - type: kv
        target: sf_email_report
        title: Emails During Session
        fields:
          - label: Total Emails
            path: total_emails
          - label: Task Emails
            path: task_emails_count
      - type: json
        target: sf_email_report
        source: all_emails
        label: Email Report Details
---

# SmartFocus

Proactive focus-session agent integrated as an Ouroboros extension skill.

## Features

- **Task prioritization** — Eisenhower matrix + deterministic scoring + TOP-3
- **Focus sessions** — explicit start/stop via agent tools, duration recommendation
- **FocusScore** — transparent 0-1 score (FocusedTimeRatio, SwitchStability, RecoveryRate, GoalProgress)
- **Proactive monitoring** — companion process checks session timing, sends nudges
- **Notification filtering** — urgent vs deferred, with explanations
- **Knowledge base** — AI Q&A saved as Markdown in vault
- **Adaptive recommendations** — observation → rationale → proposed change → accept/reject/observe
- **Configurable sources** — source_mode setting (direct/mcp/hybrid) for future direct/MCP integration; current demo uses synthetic datasets
- **Widget dashboard** — live session, FocusScore, TOP-3, Eisenhower matrix
- **Thunderbird email polling** — scans INBOX every 3 minutes, extracts [task-XXX] from subjects, handles Cyrillic headers
- **Session email report** — tracks all emails received during a focus session, available via tool and widget
- **Do Not Disturb** — enables macOS DND on session start, disables on stop (requires accessibility permissions for Control Center automation)

## Architecture

- `plugin.py` — PluginAPI registration (tools, routes, widget, settings, companion)
- `companion.py` — proactive monitoring subprocess
- `models.py` — dataclass data models (self-contained, no DB)
- `state.py` — JSON file state management
- `config.py` — constants and defaults
- `prioritize.py` — Eisenhower matrix + deterministic scoring + TOP-3
- `focus_score.py` — transparent FocusScore calculation
- `session.py` — focus session lifecycle
- `notifications.py` — notification queue and filtering
- `normalize.py` — deduplication, linking, normalization
- `adapt.py` — adaptation engine with proposals
- `knowledge.py` — AI Q&A + Markdown vault export
- `synthetic.py` — synthetic event generator for demo mode
- `email_scanner.py` — incremental Thunderbird mbox scanner, task extraction
- `dnd.py` — macOS Do Not Disturb / Focus mode toggle
- `report.py` — daily report generation

## State

All state is stored as JSON files in the skill state directory:
- `tasks.json` — task list
- `sessions.json` — session history
- `proposals.json` — adaptation proposals
- `settings.json` — user configuration
- `journal.jsonl` — action journal
- `vault/` — markdown knowledge entries
- `email_state.json` — email scan state (seen Message-IDs, byte offset)
- `session_emails.json` — emails received during each session

## Demo Mode

Call `reset_demo` tool to reset state. Call `scan_sources` with dataset_name to load synthetic data.
