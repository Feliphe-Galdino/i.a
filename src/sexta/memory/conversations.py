"""Persistência de conversas e mensagens.

As mensagens são guardadas **exatamente** como foram enviadas/recebidas da API
(lista de *content blocks* em JSON). Isso mantém o histórico *append-only*: ao
reenviar a conversa, o prefixo é idêntico byte a byte, o que preserva o cache de
prompt e a validade dos blocos de raciocínio. ``display_text`` guarda a versão
legível (usada na interface e na busca).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .db import Database, utcnow
from .text import fts_query

TITLE_MAX = 60


def make_title(text: str) -> str:
    title = " ".join(text.split())
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1].rstrip() + "…"


def text_of(content: list[dict[str, Any]]) -> str:
    return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()


class ConversationService:
    def __init__(self, db: Database):
        self.db = db

    def create(self, *, system_prompt: str, title: str = "Nova conversa") -> dict[str, Any]:
        conv_id = uuid.uuid4().hex[:16]
        now = utcnow()
        self.db.execute(
            "INSERT INTO conversations (id, title, system_prompt, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, make_title(title), system_prompt, now, now),
        )
        conv = self.get(conv_id)
        assert conv is not None
        return conv

    def get(self, conv_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM conversations WHERE id = ?", (conv_id,))

    def list(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT c.id, c.title, c.last_tier, c.last_model, c.created_at, c.updated_at,
                      (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.kind != 'tool_results') AS message_count
               FROM conversations c ORDER BY c.updated_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )

    def rename(self, conv_id: str, title: str) -> None:
        self.db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (make_title(title) or "Conversa", utcnow(), conv_id),
        )

    def set_route(self, conv_id: str, *, tier: str, model: str) -> None:
        self.db.execute(
            "UPDATE conversations SET last_tier = ?, last_model = ?, updated_at = ? WHERE id = ?",
            (tier, model, utcnow(), conv_id),
        )

    def delete(self, conv_id: str) -> bool:
        cur = self.db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return cur.rowcount > 0

    # --- Mensagens ----------------------------------------------------------
    def append(
        self,
        conv_id: str,
        *,
        role: str,
        kind: str,
        content: list[dict[str, Any]],
        display_text: str = "",
        model: str | None = None,
        task_id: str | None = None,
    ) -> int:
        now = utcnow()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO messages (conversation_id, role, kind, content, display_text, model, task_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv_id, role, kind, json.dumps(content, ensure_ascii=False), display_text, model, task_id, now),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
            return int(cur.lastrowid)

    def api_messages(self, conv_id: str) -> list[dict[str, Any]]:
        """Histórico no formato da API, na ordem exata em que foi gravado."""
        rows = self.db.query("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conv_id,))
        return [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]

    def history_chars(self, conv_id: str) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) AS n FROM messages WHERE conversation_id = ?",
            (conv_id,),
        )
        return int(row["n"]) if row else 0

    def view(self, conv_id: str) -> list[dict[str, Any]]:
        """Histórico simplificado para a interface (texto, raciocínio e ferramentas)."""
        rows = self.db.query(
            "SELECT id, role, kind, content, display_text, model, task_id, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        )
        items: list[dict[str, Any]] = []
        tool_index: dict[str, dict[str, Any]] = {}
        for row in rows:
            content = json.loads(row["content"])
            if row["kind"] == "user":
                items.append(
                    {"id": row["id"], "role": "user", "text": row["display_text"], "created_at": row["created_at"]}
                )
                continue
            if row["kind"] == "tool_results":
                for block in content:
                    if block.get("type") == "tool_result" and block.get("tool_use_id") in tool_index:
                        call = tool_index[block["tool_use_id"]]
                        call["result"] = _result_text(block.get("content"))
                        call["is_error"] = bool(block.get("is_error"))
                continue
            # Mensagem do assistente
            item: dict[str, Any] = {
                "id": row["id"],
                "role": "assistant",
                "text": text_of(content),
                "thinking": "\n\n".join(
                    b.get("thinking", "") for b in content if b.get("type") == "thinking" and b.get("thinking")
                ),
                "tools": [],
                "model": row["model"],
                "task_id": row["task_id"],
                "created_at": row["created_at"],
            }
            for block in content:
                if block.get("type") in ("tool_use", "server_tool_use"):
                    call = {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input"),
                        "server": block.get("type") == "server_tool_use",
                        "result": None,
                        "is_error": False,
                    }
                    tool_index[str(block.get("id"))] = call
                    item["tools"].append(call)
            items.append(item)
        return items

    def search_messages(self, text: str, *, limit: int = 10) -> list[dict[str, Any]]:
        match = fts_query(text)
        if not match:
            return []
        return self.db.query(
            """SELECT m.id, m.conversation_id, c.title, m.role, m.created_at,
                      snippet(messages_fts, 0, '«', '»', '…', 24) AS snippet
               FROM messages_fts
               JOIN messages m ON m.id = messages_fts.rowid
               JOIN conversations c ON c.id = m.conversation_id
               WHERE messages_fts MATCH ?
               ORDER BY bm25(messages_fts) LIMIT ?""",
            (match, limit),
        )


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""
