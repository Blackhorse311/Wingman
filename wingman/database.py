"""SQLite database layer for tracking seen items and watcher state."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Database:
    """Manages SQLite storage for Wingman state."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._create_tables()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._connect()
        return self._conn  # type: ignore[return-value]

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                repo_or_context TEXT NOT NULL,
                title TEXT,
                body TEXT,
                author TEXT,
                url TEXT,
                classification TEXT,
                severity TEXT,
                summary TEXT,
                notified_at TEXT,
                first_seen_at TEXT NOT NULL,
                created_at TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_seen_source
                ON seen_items(source, source_id, item_type);

            CREATE TABLE IF NOT EXISTS forge_tokens (
                id INTEGER PRIMARY KEY,
                token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS watcher_state (
                watcher_name TEXT PRIMARY KEY,
                last_check_at TEXT,
                last_successful_at TEXT,
                consecutive_failures INTEGER DEFAULT 0,
                metadata TEXT
            );
        """)
        self.conn.commit()

    # -- seen_items operations --

    def is_seen(self, source: str, source_id: str, item_type: str) -> bool:
        """Check if an item has already been recorded."""
        row = self.conn.execute(
            "SELECT 1 FROM seen_items WHERE source=? AND source_id=? AND item_type=?",
            (source, source_id, item_type),
        ).fetchone()
        return row is not None

    def mark_seen(
        self,
        source: str,
        source_id: str,
        item_type: str,
        repo_or_context: str,
        title: str = "",
        body: str = "",
        author: str = "",
        url: str = "",
        created_at: str = "",
    ) -> None:
        """Insert a new item into seen_items. Ignores duplicates."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT OR IGNORE INTO seen_items
               (source, source_id, item_type, repo_or_context,
                title, body, author, url, first_seen_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source, source_id, item_type, repo_or_context,
             title, body, author, url, now, created_at),
        )
        self.conn.commit()

    def update_triage(
        self,
        source: str,
        source_id: str,
        item_type: str,
        classification: str,
        severity: str,
        summary: str,
    ) -> None:
        """Update triage results for a seen item."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE seen_items
               SET classification=?, severity=?, summary=?, notified_at=?
               WHERE source=? AND source_id=? AND item_type=?""",
            (classification, severity, summary, now,
             source, source_id, item_type),
        )
        self.conn.commit()

    # -- watcher_state operations --

    def get_watcher_state(self, watcher_name: str) -> dict[str, Any] | None:
        """Get the current state for a watcher."""
        row = self.conn.execute(
            "SELECT * FROM watcher_state WHERE watcher_name=?",
            (watcher_name,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("metadata"):
            result["metadata"] = json.loads(result["metadata"])
        else:
            result["metadata"] = {}
        return result

    def update_watcher_state(
        self,
        watcher_name: str,
        successful: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update watcher state after a check cycle."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_watcher_state(watcher_name)

        if existing is None:
            meta = json.dumps(metadata) if metadata else "{}"
            self.conn.execute(
                """INSERT INTO watcher_state
                   (watcher_name, last_check_at, last_successful_at,
                    consecutive_failures, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (watcher_name, now, now if successful else None,
                 0 if successful else 1, meta),
            )
        else:
            failures = 0 if successful else existing["consecutive_failures"] + 1
            merged_meta = existing.get("metadata", {})
            if metadata:
                merged_meta.update(metadata)
            self.conn.execute(
                """UPDATE watcher_state
                   SET last_check_at=?,
                       last_successful_at=CASE WHEN ? THEN ? ELSE last_successful_at END,
                       consecutive_failures=?,
                       metadata=?
                   WHERE watcher_name=?""",
                (now, successful, now, failures,
                 json.dumps(merged_meta), watcher_name),
            )
        self.conn.commit()

    def get_consecutive_failures(self, watcher_name: str) -> int:
        """Get the consecutive failure count for a watcher."""
        state = self.get_watcher_state(watcher_name)
        if state is None:
            return 0
        return state.get("consecutive_failures", 0)

    def is_first_run(self, watcher_name: str) -> bool:
        """Check if a watcher has never completed a successful check."""
        state = self.get_watcher_state(watcher_name)
        return state is None or state.get("last_successful_at") is None

    # -- forge_tokens operations --

    def get_forge_token(self) -> str | None:
        """Get the cached Forge API token."""
        row = self.conn.execute(
            "SELECT token FROM forge_tokens ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["token"] if row else None

    def save_forge_token(self, token: str) -> None:
        """Save a new Forge API token, replacing any existing one."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("DELETE FROM forge_tokens")
        self.conn.execute(
            "INSERT INTO forge_tokens (token, created_at) VALUES (?, ?)",
            (token, now),
        )
        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
