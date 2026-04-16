from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from core.config import get_settings

_SCHEMA_VERSION = 4

_MIGRATIONS: Dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
        content TEXT NOT NULL,
        session_id TEXT NOT NULL,
        agent_name TEXT DEFAULT 'main',
        telegram_message_id INTEGER,
        timestamp REAL NOT NULL,
        metadata TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(timestamp);

    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        agent_name TEXT NOT NULL DEFAULT 'main',
        claude_session_id TEXT,
        created_at REAL NOT NULL,
        last_active REAL NOT NULL,
        summary TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived','compacted')),
        metadata TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS agents (
        name TEXT PRIMARY KEY,
        scope TEXT NOT NULL CHECK(scope IN ('global','project','ephemeral')),
        project TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','killed')),
        created_at REAL NOT NULL,
        last_used REAL,
        soul_path TEXT,
        permissions TEXT DEFAULT '{}',
        skills TEXT DEFAULT '[]',
        metadata TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        schedule_type TEXT NOT NULL CHECK(schedule_type IN ('cron','interval','once')),
        schedule_value TEXT NOT NULL,
        next_run REAL,
        last_run REAL,
        last_result TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','failed')),
        notify INTEGER NOT NULL DEFAULT 1,
        model TEXT DEFAULT 'haiku',
        agent_name TEXT DEFAULT 'main',
        created_at REAL NOT NULL,
        metadata TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON tasks(next_run);
    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

    CREATE TABLE IF NOT EXISTS task_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id),
        run_at REAL NOT NULL,
        duration_ms INTEGER,
        status TEXT NOT NULL CHECK(status IN ('success','failed','timeout')),
        result TEXT,
        error TEXT,
        tokens_used INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id, run_at);

    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        agent_name TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT,
        level TEXT NOT NULL CHECK(level IN ('auto','confirm_tg','confirm_terminal')),
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied','timeout')),
        code TEXT,
        created_at REAL NOT NULL,
        resolved_at REAL,
        resolved_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

    CREATE TABLE IF NOT EXISTS usage_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_name TEXT NOT NULL,
        model TEXT NOT NULL,
        timestamp REAL NOT NULL,
        duration_ms INTEGER,
        session_id TEXT,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        estimated_percent REAL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log(timestamp);

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    INSERT INTO schema_version (version) VALUES (1);
    """,
    2: """
    CREATE TABLE IF NOT EXISTS queued_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        text TEXT NOT NULL,
        media_path TEXT,
        telegram_message_id INTEGER,
        created_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','done'))
    );
    CREATE INDEX IF NOT EXISTS idx_queue_status ON queued_messages(status, created_at);

    INSERT OR REPLACE INTO schema_version (version) VALUES (2);
    """,
    3: """
    CREATE TABLE IF NOT EXISTS directory_sessions (
        directory TEXT PRIMARY KEY,
        claude_session_id TEXT NOT NULL,
        last_used REAL NOT NULL
    );

    INSERT OR REPLACE INTO schema_version (version) VALUES (3);
    """,
    4: """
    ALTER TABLE agents ADD COLUMN budget_percent REAL DEFAULT NULL;

    CREATE TABLE IF NOT EXISTS agent_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_agent TEXT NOT NULL,
        to_agent TEXT NOT NULL,
        body TEXT NOT NULL,
        timestamp REAL NOT NULL,
        read_at REAL DEFAULT NULL,
        metadata TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_agent_messages_to
        ON agent_messages(to_agent, read_at);
    CREATE INDEX IF NOT EXISTS idx_usage_log_agent_ts
        ON usage_log(agent_name, timestamp);

    INSERT OR REPLACE INTO schema_version (version) VALUES (4);
    """,
}


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = get_settings().data_dir / "caliclaw.db"
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        # Wait up to 30 seconds for locks instead of immediate SQLITE_BUSY error
        await self._db.execute("PRAGMA busy_timeout=30000")
        # Synchronous=NORMAL is safe with WAL and faster than FULL
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._migrate()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not connected"
        return self._db

    async def _migrate(self) -> None:
        current = 0
        try:
            async with self.db.execute("SELECT MAX(version) FROM schema_version") as cur:
                row = await cur.fetchone()
                if row and row[0]:
                    current = row[0]
        except aiosqlite.OperationalError:
            pass

        for ver in sorted(_MIGRATIONS.keys()):
            if ver > current:
                await self.db.executescript(_MIGRATIONS[ver])
        await self.db.commit()

    # ── Messages ──

    async def save_message(
        self,
        role: str,
        content: str,
        session_id: str,
        agent_name: str = "main",
        telegram_message_id: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> int:
        ts = time.time()
        meta_json = json.dumps(metadata or {})
        async with self.db.execute(
            """INSERT INTO messages (role, content, session_id, agent_name,
               telegram_message_id, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (role, content, session_id, agent_name, telegram_message_id, ts, meta_json),
        ) as cur:
            await self.db.commit()
            return cur.lastrowid  # type: ignore

    async def get_messages(
        self, session_id: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        async with self.db.execute(
            """SELECT * FROM messages WHERE session_id = ?
               ORDER BY timestamp ASC LIMIT ? OFFSET ?""",
            (session_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def count_messages(self, session_id: str) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    # ── Sessions ──

    async def create_session(
        self, session_id: str, agent_name: str = "main", metadata: Optional[Dict] = None
    ) -> None:
        ts = time.time()
        await self.db.execute(
            """INSERT OR REPLACE INTO sessions
               (id, agent_name, created_at, last_active, status, metadata)
               VALUES (?, ?, ?, ?, 'active', ?)""",
            (session_id, agent_name, ts, ts, json.dumps(metadata or {})),
        )
        await self.db.commit()

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def update_session(self, session_id: str, **kwargs: Any) -> None:
        if "claude_session_id" in kwargs or "summary" in kwargs or "status" in kwargs:
            sets = []
            vals: list = []
            for key in ("claude_session_id", "summary", "status"):
                if key in kwargs:
                    sets.append(f"{key} = ?")
                    vals.append(kwargs[key])
            sets.append("last_active = ?")
            vals.append(time.time())
            vals.append(session_id)
            await self.db.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", vals
            )
            await self.db.commit()

    async def get_active_session(self, agent_name: str = "main") -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            """SELECT * FROM sessions WHERE agent_name = ? AND status = 'active'
               ORDER BY last_active DESC LIMIT 1""",
            (agent_name,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── Agents ──

    async def save_agent(
        self,
        name: str,
        scope: str,
        project: Optional[str] = None,
        soul_path: Optional[str] = None,
        permissions: Optional[Dict] = None,
        skills: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        ts = time.time()
        await self.db.execute(
            """INSERT OR REPLACE INTO agents
               (name, scope, project, created_at, soul_path, permissions,
                skills, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, scope, project, ts, soul_path,
                json.dumps(permissions or {}),
                json.dumps(skills or []),
                json.dumps(metadata or {}),
            ),
        )
        await self.db.commit()

    async def get_agent(self, name: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM agents WHERE name = ?", (name,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_agents(
        self, scope: Optional[str] = None, status: str = "active"
    ) -> List[Dict[str, Any]]:
        if scope:
            query = "SELECT * FROM agents WHERE scope = ? AND status = ?"
            params: tuple = (scope, status)
        else:
            query = "SELECT * FROM agents WHERE status = ?"
            params = (status,)
        async with self.db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def update_agent_status(self, name: str, status: str) -> None:
        await self.db.execute(
            "UPDATE agents SET status = ?, last_used = ? WHERE name = ?",
            (status, time.time(), name),
        )
        await self.db.commit()

    # ��─ Tasks (scheduled) ──

    async def create_task(
        self,
        name: str,
        prompt: str,
        schedule_type: str,
        schedule_value: str,
        next_run: Optional[float] = None,
        notify: bool = True,
        model: str = "haiku",
        agent_name: str = "main",
        metadata: Optional[Dict] = None,
    ) -> int:
        ts = time.time()
        async with self.db.execute(
            """INSERT INTO tasks
               (name, prompt, schedule_type, schedule_value, next_run, notify,
                model, agent_name, created_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, prompt, schedule_type, schedule_value,
                next_run or ts, int(notify), model, agent_name, ts,
                json.dumps(metadata or {}),
            ),
        ) as cur:
            await self.db.commit()
            return cur.lastrowid  # type: ignore

    async def get_due_tasks(self) -> List[Dict[str, Any]]:
        now = time.time()
        async with self.db.execute(
            """SELECT * FROM tasks
               WHERE status = 'active' AND next_run <= ?
               ORDER BY next_run ASC""",
            (now,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def update_task_after_run(
        self,
        task_id: int,
        next_run: Optional[float],
        result: str,
        status: str = "active",
    ) -> None:
        now = time.time()
        await self.db.execute(
            """UPDATE tasks SET last_run = ?, last_result = ?,
               next_run = ?, status = ? WHERE id = ?""",
            (now, result, next_run, status, task_id),
        )
        await self.db.commit()

    async def log_task_run(
        self,
        task_id: int,
        duration_ms: int,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        tokens_used: int = 0,
    ) -> None:
        await self.db.execute(
            """INSERT INTO task_runs
               (task_id, run_at, duration_ms, status, result, error, tokens_used)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, time.time(), duration_ms, status, result, error, tokens_used),
        )
        await self.db.commit()

    # ── Approvals ──

    async def create_approval(
        self,
        approval_id: str,
        agent_name: str,
        action: str,
        level: str,
        reason: Optional[str] = None,
        code: Optional[str] = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO approvals
               (id, agent_name, action, reason, level, code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (approval_id, agent_name, action, reason, level, code, time.time()),
        )
        await self.db.commit()

    async def resolve_approval(
        self, approval_id: str, status: str, resolved_by: str
    ) -> None:
        await self.db.execute(
            """UPDATE approvals SET status = ?, resolved_at = ?, resolved_by = ?
               WHERE id = ?""",
            (status, time.time(), resolved_by, approval_id),
        )
        await self.db.commit()

    async def get_pending_approval(self, code: str) -> Optional[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT * FROM approvals WHERE code = ? AND status = 'pending'", (code,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── Usage log ──

    async def log_usage(
        self,
        agent_name: str,
        model: str,
        duration_ms: int = 0,
        session_id: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_percent: float = 0,
    ) -> None:
        await self.db.execute(
            """INSERT INTO usage_log
               (agent_name, model, timestamp, duration_ms, session_id,
                prompt_tokens, completion_tokens, estimated_percent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_name, model, time.time(), duration_ms,
                session_id, prompt_tokens, completion_tokens, estimated_percent,
            ),
        )
        await self.db.commit()

    async def get_usage_today(self) -> float:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        async with self.db.execute(
            "SELECT SUM(estimated_percent) FROM usage_log WHERE timestamp >= ?",
            (today_start,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else 0.0

    # ── Agent mailbox (inter-agent messaging) ──

    async def send_agent_message(
        self,
        from_agent: str,
        to_agent: str,
        body: str,
        metadata: Optional[Dict] = None,
    ) -> int:
        async with self.db.execute(
            """INSERT INTO agent_messages
               (from_agent, to_agent, body, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (from_agent, to_agent, body, time.time(), json.dumps(metadata or {})),
        ) as cur:
            await self.db.commit()
            return cur.lastrowid  # type: ignore

    async def get_agent_messages(
        self,
        agent_name: str,
        unread_only: bool = True,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        if unread_only:
            query = (
                "SELECT * FROM agent_messages "
                "WHERE to_agent = ? AND read_at IS NULL "
                "ORDER BY timestamp DESC LIMIT ?"
            )
        else:
            query = (
                "SELECT * FROM agent_messages WHERE to_agent = ? "
                "ORDER BY timestamp DESC LIMIT ?"
            )
        async with self.db.execute(query, (agent_name, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_agent_message_read(self, message_id: int) -> None:
        await self.db.execute(
            "UPDATE agent_messages SET read_at = ? WHERE id = ?",
            (time.time(), message_id),
        )
        await self.db.commit()

    # ── Queued messages ──

    async def enqueue_message(
        self,
        session_id: str,
        sender: str,
        text: str,
        media_path: Optional[str] = None,
        telegram_message_id: Optional[int] = None,
    ) -> int:
        async with self.db.execute(
            """INSERT INTO queued_messages
               (session_id, sender, text, media_path, telegram_message_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, sender, text, media_path, telegram_message_id, time.time()),
        ) as cur:
            await self.db.commit()
            return cur.lastrowid  # type: ignore

    async def get_pending_queue(self, session_id: str) -> List[Dict[str, Any]]:
        async with self.db.execute(
            """SELECT * FROM queued_messages
               WHERE session_id = ? AND status = 'pending'
               ORDER BY created_at ASC""",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_queue_done(self, ids: List[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        await self.db.execute(
            f"UPDATE queued_messages SET status = 'done' WHERE id IN ({placeholders})",
            ids,
        )
        await self.db.commit()

    async def clear_old_queue(self, older_than_hours: int = 24) -> None:
        cutoff = time.time() - older_than_hours * 3600
        await self.db.execute(
            "DELETE FROM queued_messages WHERE status = 'done' AND created_at < ?",
            (cutoff,),
        )
        await self.db.commit()

    # ── Directory sessions (per-working-dir Claude session continuity) ──

    async def get_directory_session(self, directory: str) -> Optional[str]:
        """Get saved Claude session_id for a directory."""
        async with self.db.execute(
            "SELECT claude_session_id FROM directory_sessions WHERE directory = ?",
            (directory,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def save_directory_session(self, directory: str, claude_session_id: str) -> None:
        """Save Claude session_id for a directory."""
        await self.db.execute(
            """INSERT OR REPLACE INTO directory_sessions
               (directory, claude_session_id, last_used)
               VALUES (?, ?, ?)""",
            (directory, claude_session_id, time.time()),
        )
        await self.db.commit()
