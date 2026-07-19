"""SQLite-backed state management for SmartFocus.

All state is persisted in a SQLite database (WAL mode) under the skill
state directory. This replaces the previous JSON-file approach and provides
atomic transactions, cross-process concurrency (in-process extension +
companion subprocess), and eliminates read-modify-write race conditions.

The public API is identical to the previous JSON version — callers
(session.py, plugin.py, adapt.py, etc.) require no changes to their
data-access patterns. The only difference is the storage engine.

Vault Markdown files remain on disk (SQLite is not a good fit for
human-readable .md files).
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from datetime import datetime
from typing import Any, Callable

_STATE_DIR: str = ""
_DB_PATH: str = ""


# ─── Initialization ───────────────────────────────────


def init_state(state_dir: str) -> None:
    """Set the state directory, migrate legacy JSON, and create schema."""
    global _STATE_DIR, _DB_PATH
    _STATE_DIR = str(state_dir)
    p = pathlib.Path(_STATE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    (p / "vault").mkdir(parents=True, exist_ok=True)
    _DB_PATH = str(p / "smartfocus.db")
    _migrate_json_files()
    _init_schema()


def get_state_dir() -> str:
    return _STATE_DIR


def _get_conn() -> sqlite3.Connection:
    """Open a fresh connection with WAL mode and busy timeout."""
    conn = sqlite3.connect(_DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _init_schema() -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    actor TEXT
                );
                CREATE TABLE IF NOT EXISTS email_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_emails_sid ON session_emails(session_id);
            """)
    finally:
        conn.close()


# ─── Legacy JSON migration (one-time) ─────────────────


def _migrate_json_files() -> None:
    """Import existing JSON state files into SQLite, then rename as backup."""
    p = pathlib.Path(_STATE_DIR)
    if (p / "smartfocus.db").exists():
        return  # Already migrated

    json_files = [
        "tasks.json", "sessions.json", "proposals.json",
        "settings.json", "knowledge.json",
        "email_state.json", "session_emails.json",
    ]
    has_any = any((p / f).exists() for f in json_files)
    has_any = has_any or (p / "journal.jsonl").exists()
    if not has_any:
        return  # Fresh install, nothing to migrate

    _init_schema()
    conn = _get_conn()
    try:
        with conn:
            _migrate_json_list(conn, p / "tasks.json", "tasks")
            _migrate_json_list(conn, p / "sessions.json", "sessions")
            _migrate_json_list(conn, p / "proposals.json", "proposals")
            _migrate_json_dict_kv(conn, p / "settings.json", "settings")
            _migrate_json_list(conn, p / "knowledge.json", "knowledge")
            _migrate_json_dict_kv(conn, p / "email_state.json", "email_state")
            _migrate_session_emails(conn, p / "session_emails.json")
            _migrate_journal(conn, p / "journal.jsonl")
        # Rename old files as backups
        for fname in json_files + ["journal.jsonl"]:
            fpath = p / fname
            if fpath.exists():
                backup = fpath.with_suffix(f".migrated{fpath.suffix}")
                try:
                    fpath.rename(backup)
                except OSError:
                    pass
    finally:
        conn.close()


def _migrate_json_list(conn: sqlite3.Connection, fpath: pathlib.Path, table: str) -> None:
    if not fpath.exists():
        return
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, list):
        return
    for item in data:
        if isinstance(item, dict):
            item_id = item.get("id", "")
            # sessions/proposals have a status column; tasks/knowledge do not
            if table in ("sessions", "proposals"):
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} (id, status, data) VALUES (?, ?, ?)",
                    (item_id, item.get("status", ""), json.dumps(item, ensure_ascii=False)),
                )
            elif table == "tasks":
                conn.execute(
                    "INSERT OR REPLACE INTO tasks (id, data) VALUES (?, ?)",
                    (item_id, json.dumps(item, ensure_ascii=False)),
                )
            elif table == "knowledge":
                conn.execute(
                    "INSERT INTO knowledge (data, created_at) VALUES (?, ?)",
                    (json.dumps(item, ensure_ascii=False),
                     item.get("timestamp", datetime.now().isoformat())),
                )


def _migrate_json_dict_kv(conn: sqlite3.Connection, fpath: pathlib.Path, table: str) -> None:
    if not fpath.exists():
        return
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        conn.execute(
            f"INSERT OR REPLACE INTO {table} (key, value) VALUES (?, ?)",
            (str(key), json.dumps(value, ensure_ascii=False)),
        )


def _migrate_session_emails(conn: sqlite3.Connection, fpath: pathlib.Path) -> None:
    if not fpath.exists():
        return
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    for session_id, emails in data.items():
        if isinstance(emails, list):
            for email in emails:
                conn.execute(
                    "INSERT INTO session_emails (session_id, data) VALUES (?, ?)",
                    (session_id, json.dumps(email, ensure_ascii=False)),
                )


def _migrate_journal(conn: sqlite3.Connection, fpath: pathlib.Path) -> None:
    if not fpath.exists():
        return
    try:
        text = fpath.read_text(encoding="utf-8").strip()
    except OSError:
        return
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            conn.execute(
                "INSERT INTO journal (timestamp, action, details, actor) VALUES (?, ?, ?, ?)",
                (entry.get("timestamp", ""), entry.get("action", ""),
                 entry.get("details", ""), entry.get("actor", "system")),
            )
        except json.JSONDecodeError:
            pass


# ─── Tasks ────────────────────────────────────────────


def get_tasks() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT data FROM tasks").fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def save_tasks(tasks: list[dict]) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM tasks")
            conn.executemany(
                "INSERT INTO tasks (id, data) VALUES (?, ?)",
                [(t.get("id", ""), json.dumps(t, ensure_ascii=False)) for t in tasks],
            )
    finally:
        conn.close()


def append_task(task: dict) -> None:
    """Atomic insert of a single task."""
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO tasks (id, data) VALUES (?, ?)",
                (task.get("id", ""), json.dumps(task, ensure_ascii=False)),
            )
    finally:
        conn.close()


# ─── Sessions ─────────────────────────────────────────


def get_sessions() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT data FROM sessions ORDER BY rowid").fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def save_sessions(sessions: list[dict]) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM sessions")
            conn.executemany(
                "INSERT INTO sessions (id, status, data) VALUES (?, ?, ?)",
                [(s.get("id", ""), s.get("status", ""),
                  json.dumps(s, ensure_ascii=False)) for s in sessions],
            )
    finally:
        conn.close()


def append_session(session: dict) -> None:
    """Atomic insert of a single session."""
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (id, status, data) VALUES (?, ?, ?)",
                (session.get("id", ""), session.get("status", ""),
                 json.dumps(session, ensure_ascii=False)),
            )
    finally:
        conn.close()


def update_session_by_id(session_id: str, session_dict: dict) -> bool:
    """Atomic replace of a session by ID."""
    conn = _get_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE sessions SET data=?, status=? WHERE id=?",
                (json.dumps(session_dict, ensure_ascii=False),
                 session_dict.get("status", ""), session_id),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def modify_session(session_id: str, modifier_fn: Callable[[dict], Any]) -> Any:
    """Atomically read-modify-write a session. Returns modifier_fn result or None."""
    conn = _get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT data FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if not row:
                return None
            session = json.loads(row[0])
            result = modifier_fn(session)
            conn.execute(
                "UPDATE sessions SET data=?, status=? WHERE id=?",
                (json.dumps(session, ensure_ascii=False),
                 session.get("status", ""), session_id),
            )
            return result
    finally:
        conn.close()


def get_active_session() -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT data FROM sessions WHERE status='active' LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


# ─── Proposals ────────────────────────────────────────


def get_proposals(status: str | None = None) -> list[dict]:
    conn = _get_conn()
    try:
        if status:
            rows = conn.execute(
                "SELECT data FROM proposals WHERE status=? ORDER BY rowid", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT data FROM proposals ORDER BY rowid").fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def save_proposals(proposals: list[dict]) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM proposals")
            conn.executemany(
                "INSERT INTO proposals (id, status, data) VALUES (?, ?, ?)",
                [(p.get("id", ""), p.get("status", ""),
                  json.dumps(p, ensure_ascii=False)) for p in proposals],
            )
    finally:
        conn.close()


def add_proposal(proposal: dict) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO proposals (id, status, data) VALUES (?, ?, ?)",
                (proposal.get("id", ""), proposal.get("status", ""),
                 json.dumps(proposal, ensure_ascii=False)),
            )
    finally:
        conn.close()


def update_proposal(proposal_id: str, updates: dict) -> bool:
    conn = _get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT data FROM proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            if not row:
                return False
            proposal = json.loads(row[0])
            proposal.update(updates)
            conn.execute(
                "UPDATE proposals SET data=?, status=? WHERE id=?",
                (json.dumps(proposal, ensure_ascii=False),
                 proposal.get("status", ""), proposal_id),
            )
            return True
    finally:
        conn.close()


# ─── Settings ─────────────────────────────────────────


def get_setting(key: str, default: Any = None) -> Any:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default
    finally:
        conn.close()


def get_all_settings() -> dict:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}
    finally:
        conn.close()


def set_setting(key: str, value: Any) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
    finally:
        conn.close()


def set_settings(updates: dict) -> None:
    conn = _get_conn()
    try:
        with conn:
            for key, value in updates.items():
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
    finally:
        conn.close()


# ─── Knowledge ────────────────────────────────────────


def get_knowledge_entries(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT data FROM knowledge ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def save_knowledge_entry(entry: dict) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO knowledge (data, created_at) VALUES (?, ?)",
                (json.dumps(entry, ensure_ascii=False), datetime.now().isoformat()),
            )
    finally:
        conn.close()


# ─── Journal ──────────────────────────────────────────


def log_action(action: str, details: str, actor: str = "system") -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO journal (timestamp, action, details, actor) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), action, details, actor),
            )
    finally:
        conn.close()


def get_journal(limit: int = 100) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT timestamp, action, details, actor FROM journal ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"timestamp": r[0], "action": r[1], "details": r[2], "actor": r[3]}
                for r in rows]
    finally:
        conn.close()


# ─── Vault (files, not SQLite) ────────────────────────


def get_vault_dir() -> pathlib.Path:
    v = pathlib.Path(_STATE_DIR) / "vault"
    v.mkdir(parents=True, exist_ok=True)
    return v


# ─── Email state ──────────────────────────────────────


def get_email_state() -> dict:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM email_state").fetchall()
        if not rows:
            return {"seen_ids": [], "offset": 0}
        result = {r[0]: json.loads(r[1]) for r in rows}
        result.setdefault("seen_ids", [])
        result.setdefault("offset", 0)
        return result
    finally:
        conn.close()


def save_email_state(data: dict) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM email_state")
            for key, value in data.items():
                conn.execute(
                    "INSERT INTO email_state (key, value) VALUES (?, ?)",
                    (str(key), json.dumps(value, ensure_ascii=False)),
                )
    finally:
        conn.close()


# ─── Session emails ───────────────────────────────────


def get_session_emails(session_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT data FROM session_emails WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def add_session_email(session_id: str, email: dict) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO session_emails (session_id, data) VALUES (?, ?)",
                (session_id, json.dumps(email, ensure_ascii=False)),
            )
    finally:
        conn.close()


def get_all_session_emails() -> dict:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT session_id, data FROM session_emails ORDER BY id"
        ).fetchall()
        result: dict[str, list[dict]] = {}
        for sid, data in rows:
            result.setdefault(sid, []).append(json.loads(data))
        return result
    finally:
        conn.close()


# ─── Reset ────────────────────────────────────────────


def reset_state() -> None:
    """Clear all state data (for demo reset). Keeps settings DB structure."""
    conn = _get_conn()
    try:
        with conn:
            for table in ["tasks", "sessions", "proposals", "knowledge",
                          "journal", "email_state", "session_emails"]:
                conn.execute(f"DELETE FROM {table}")
            # Clear day-summary trigger so auto-summary fires after a demo reset
            conn.execute("DELETE FROM settings WHERE key='last_day_summary_date'")
    finally:
        conn.close()
    # Clear vault markdown files
    vp = pathlib.Path(_STATE_DIR) / "vault"
    if vp.exists():
        for f in vp.iterdir():
            if f.is_file():
                f.unlink()


# ─── Task status updates ──────────────────────────────


def update_task_status(task_id: str, status: str) -> bool:
    """Update a task's status. Returns True if task found and updated."""
    conn = _get_conn()
    try:
        with conn:
            row = conn.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return False
            task = json.loads(row[0])
            task["status"] = status
            if status == "done":
                task["completed_at"] = datetime.now().isoformat()
            conn.execute(
                "UPDATE tasks SET data=? WHERE id=?",
                (json.dumps(task, ensure_ascii=False), task_id),
            )
            return True
    finally:
        conn.close()


def get_tasks_by_status(status: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT data FROM tasks").fetchall()
        return [json.loads(r[0]) for r in rows
                if json.loads(r[0]).get("status") == status]
    finally:
        conn.close()


# ─── Date-filtered sessions ────────────────────────────


def get_sessions_for_date(date_str: str) -> list[dict]:
    """Get sessions that started on the given date (YYYY-MM-DD)."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT data FROM sessions ORDER BY rowid").fetchall()
        sessions = [json.loads(r[0]) for r in rows]
        return [s for s in sessions if (s.get("start_time", "")[:10] == date_str)]
    finally:
        conn.close()


def get_today_sessions() -> list[dict]:
    """Get sessions that started today."""
    return get_sessions_for_date(datetime.now().strftime("%Y-%m-%d"))


def get_last_completed_session() -> dict | None:
    """Get the most recently completed session."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT data FROM sessions WHERE status IN ('completed','auto_stopped') "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()
