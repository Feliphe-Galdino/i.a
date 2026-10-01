"""Banco de dados local (SQLite) com migrações versionadas.

Por que SQLite?
* Zero instalação, um único arquivo, transações ACID e backup fácil (copiar o arquivo).
* FTS5 embutido: busca textual rápida (BM25) para memórias e conversas, sem servidor.
* Suficiente para um assistente pessoal; se um dia precisar escalar, a camada de
  serviços isola o resto do sistema do banco.

Para evoluir o esquema, adicione um novo item ao final de ``MIGRATIONS``. Nunca
edite uma migração já publicada: o banco do usuário já a executou.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # v1 — esquema inicial
    """
    CREATE TABLE conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        last_tier TEXT,
        last_model TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        kind TEXT NOT NULL,
        content TEXT NOT NULL,
        display_text TEXT NOT NULL DEFAULT '',
        model TEXT,
        task_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_messages_conv ON messages(conversation_id, id);

    CREATE VIRTUAL TABLE messages_fts USING fts5(
        display_text, content='messages', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    );
    CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, display_text) VALUES (new.id, new.display_text);
    END;
    CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, display_text)
        VALUES ('delete', old.id, old.display_text);
    END;

    CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'geral',
        tags TEXT NOT NULL DEFAULT '',
        importance INTEGER NOT NULL DEFAULT 3,
        pinned INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'user',
        conversation_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_accessed_at TEXT,
        access_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_memories_category ON memories(category);

    CREATE VIRTUAL TABLE memories_fts USING fts5(
        content, category, tags, content='memories', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    );
    CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content, category, tags)
        VALUES (new.id, new.content, new.category, new.tags);
    END;
    CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content, category, tags)
        VALUES ('delete', old.id, old.content, old.category, old.tags);
    END;
    CREATE TRIGGER memories_au AFTER UPDATE OF content, category, tags ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content, category, tags)
        VALUES ('delete', old.id, old.content, old.category, old.tags);
        INSERT INTO memories_fts(rowid, content, category, tags)
        VALUES (new.id, new.content, new.category, new.tags);
    END;

    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        conversation_id TEXT,
        status TEXT NOT NULL,
        input_preview TEXT NOT NULL DEFAULT '',
        agent TEXT,
        tier TEXT,
        model TEXT,
        effort TEXT,
        reasons TEXT NOT NULL DEFAULT '[]',
        error TEXT,
        cost_usd REAL NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE INDEX idx_tasks_started ON tasks(started_at);

    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        task_id TEXT,
        conversation_id TEXT,
        event TEXT NOT NULL,
        tool TEXT,
        capability TEXT,
        risk TEXT,
        decision TEXT,
        detail TEXT NOT NULL DEFAULT '{}',
        success INTEGER,
        duration_ms INTEGER
    );
    CREATE INDEX idx_audit_ts ON audit_log(ts);

    CREATE TABLE usage_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        task_id TEXT,
        conversation_id TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens INTEGER NOT NULL DEFAULT 0,
        web_searches INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_usage_ts ON usage_log(ts);

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """Conexão SQLite compartilhada e protegida por lock (uso pessoal, 1 processo)."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self.migrate()

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        with self._lock:
            version = self.schema_version
            for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
                self._conn.execute("BEGIN")
                try:
                    for statement in _split_sql(script):
                        self._conn.execute(statement)
                    self._conn.execute(f"PRAGMA user_version = {index}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _split_sql(script: str) -> list[str]:
    """Divide um script em comandos, respeitando blocos BEGIN...END de triggers."""
    statements: list[str] = []
    buffer: list[str] = []
    depth = 0
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        buffer.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            depth += 1
        if depth and upper.startswith("END;"):
            depth -= 1
            statements.append("\n".join(buffer))
            buffer = []
            continue
        if not depth and stripped.endswith(";"):
            statements.append("\n".join(buffer))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements
