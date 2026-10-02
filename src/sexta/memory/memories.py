"""Memória de longo prazo da Sexta-Feira.

Cada memória é um fato curto e autocontido ("O usuário prefere respostas em
tópicos"), com categoria, tags, importância (1–5) e a opção *fixada* (sempre
incluída no contexto). A recuperação é híbrida: FTS5/BM25 (palavras) + embeddings
locais (significado, ver ``semantic.py``) + importância, então apenas as memórias
relevantes vão para cada conversa — nunca o histórico inteiro.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .db import Database, utcnow
from .semantic import SemanticIndex, rrf_merge
from .text import fts_query, normalize

CATEGORIES: dict[str, str] = {
    "perfil": "Quem você é: nome, profissão, rotina, objetivos",
    "preferencias": "Como você gosta que as coisas sejam feitas",
    "projetos": "Projetos em andamento, decisões e status",
    "conhecimento": "Fatos, conceitos e referências úteis",
    "correcoes": "Correções e instruções que você me deu",
    "tarefas": "Compromissos, pendências e lembretes",
    "pessoas": "Pessoas e contatos relevantes",
    "geral": "Outros",
}

MAX_CONTENT_CHARS = 2_000


@dataclass
class Memory:
    id: int
    content: str
    category: str
    tags: list[str]
    importance: int
    pinned: bool
    source: str
    conversation_id: str | None
    created_at: str
    updated_at: str
    last_accessed_at: str | None
    access_count: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Memory:
        return cls(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            tags=[t for t in row["tags"].split(",") if t],
            importance=row["importance"],
            pinned=bool(row["pinned"]),
            source=row["source"],
            conversation_id=row["conversation_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_tags(tags: list[str] | str | None) -> str:
    if not tags:
        return ""
    items = tags.split(",") if isinstance(tags, str) else tags
    cleaned = []
    for tag in items:
        tag = tag.strip().lower().replace(",", " ")
        if tag and tag not in cleaned:
            cleaned.append(tag[:40])
    return ",".join(cleaned[:12])


def _clean_category(category: str | None) -> str:
    value = (category or "geral").strip().lower()
    return value[:40] or "geral"


class MemoryService:
    def __init__(self, db: Database, semantic: SemanticIndex | None = None):
        self.db = db
        self.semantic = semantic

    # --- CRUD -----------------------------------------------------------------
    def add(
        self,
        content: str,
        *,
        category: str = "geral",
        tags: list[str] | str | None = None,
        importance: int = 3,
        pinned: bool = False,
        source: str = "user",
        conversation_id: str | None = None,
    ) -> tuple[Memory, bool]:
        """Salva uma memória. Retorna ``(memoria, criada)``; duplicatas são atualizadas."""
        content = content.strip()[:MAX_CONTENT_CHARS]
        if not content:
            raise ValueError("A memória não pode ser vazia.")
        importance = max(1, min(5, int(importance)))
        existing = self.find_duplicate(content)
        if existing:
            updated = self.update(
                existing.id,
                importance=max(existing.importance, importance),
                pinned=existing.pinned or pinned,
                tags=sorted(set(existing.tags) | set(_clean_tags(tags).split(",")) - {""}),
            )
            return updated, False
        now = utcnow()
        cur = self.db.execute(
            """INSERT INTO memories (content, category, tags, importance, pinned, source,
                   conversation_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                content,
                _clean_category(category),
                _clean_tags(tags),
                importance,
                int(pinned),
                source,
                conversation_id,
                now,
                now,
            ),
        )
        memory = self.get(cur.lastrowid)
        assert memory is not None
        if self.semantic:
            self.semantic.index(memory.id, memory.content)
        return memory, True

    def get(self, memory_id: int) -> Memory | None:
        row = self.db.query_one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return Memory.from_row(row) if row else None

    def update(self, memory_id: int, **fields: Any) -> Memory:
        current = self.get(memory_id)
        if current is None:
            raise KeyError(f"Memória {memory_id} não encontrada.")
        values: dict[str, Any] = {}
        if "content" in fields and fields["content"] is not None:
            content = str(fields["content"]).strip()[:MAX_CONTENT_CHARS]
            if not content:
                raise ValueError("A memória não pode ser vazia.")
            values["content"] = content
        if fields.get("category") is not None:
            values["category"] = _clean_category(fields["category"])
        if fields.get("tags") is not None:
            values["tags"] = _clean_tags(fields["tags"])
        if fields.get("importance") is not None:
            values["importance"] = max(1, min(5, int(fields["importance"])))
        if fields.get("pinned") is not None:
            values["pinned"] = int(bool(fields["pinned"]))
        if values:
            values["updated_at"] = utcnow()
            assignments = ", ".join(f"{key} = :{key}" for key in values)
            self.db.execute(f"UPDATE memories SET {assignments} WHERE id = :id", {**values, "id": memory_id})
        updated = self.get(memory_id)
        assert updated is not None
        if self.semantic and "content" in values:
            self.semantic.index(updated.id, updated.content)
        return updated

    def delete(self, memory_id: int) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))  # o vetor sai em cascata
        if self.semantic:
            self.semantic.invalidate()
        return cur.rowcount > 0

    def delete_all(self) -> int:
        cur = self.db.execute("DELETE FROM memories")
        if self.semantic:
            self.semantic.invalidate()
        return cur.rowcount

    def merge(self, keep_id: int, remove_id: int) -> Memory:
        """Junta duas memórias quase iguais: mantém o texto de ``keep_id`` e une o resto."""
        if keep_id == remove_id:
            raise ValueError("Escolha duas memórias diferentes.")
        keep, remove = self.get(keep_id), self.get(remove_id)
        if keep is None or remove is None:
            raise KeyError("Memória não encontrada.")
        merged = self.update(
            keep_id,
            importance=max(keep.importance, remove.importance),
            pinned=keep.pinned or remove.pinned,
            tags=sorted(set(keep.tags) | set(remove.tags)),
        )
        self.db.execute(
            "UPDATE memories SET access_count = access_count + ? WHERE id = ?", (remove.access_count, keep_id)
        )
        self.delete(remove_id)
        return self.get(keep_id) or merged

    def duplicates(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """Pares muito parecidos pelo significado (precisa da busca semântica ativa)."""
        if not self.semantic:
            return []
        out = []
        for a_id, b_id, score in self.semantic.duplicates(limit=limit):
            a, b = self.get(a_id), self.get(b_id)
            if a and b:
                out.append({"a": a.to_dict(), "b": b.to_dict(), "similarity": round(score, 3)})
        return out

    # --- Consulta ---------------------------------------------------------
    def list(
        self,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        if query:
            return self.search(query, category=category, limit=limit, touch=False)
        sql = "SELECT * FROM memories"
        params: list[Any] = []
        if category:
            sql += " WHERE category = ?"
            params.append(category)
        sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [Memory.from_row(r) for r in self.db.query(sql, params)]

    def search(
        self,
        text: str,
        *,
        category: str | None = None,
        limit: int = 8,
        touch: bool = True,
    ) -> list[Memory]:
        lexical = self._lexical(text, category, max(limit * 3, 20))
        similar = self.semantic.search(text, limit=max(limit * 3, 20)) if self.semantic else []
        if not similar:
            memories = [Memory.from_row(r) for r in lexical[:limit]]
        else:
            # Fusão por posição (RRF) + um empurrão pequeno pela importância.
            scores = rrf_merge([r["id"] for r in lexical], [memory_id for memory_id, _ in similar])
            rows = {r["id"]: r for r in lexical}
            missing = [memory_id for memory_id, _ in similar if memory_id not in rows]
            if missing:
                marks = ",".join("?" for _ in missing)
                for row in self.db.query(f"SELECT * FROM memories WHERE id IN ({marks})", missing):
                    if not category or row["category"] == category:
                        rows[row["id"]] = row
            ranked = sorted(rows.values(), key=lambda r: -(scores.get(r["id"], 0.0) + 0.0015 * r["importance"]))
            memories = [Memory.from_row(r) for r in ranked[:limit]]
        if touch and memories:
            self._touch([m.id for m in memories])
        return memories

    def _lexical(self, text: str, category: str | None, limit: int) -> list[dict[str, Any]]:
        match = fts_query(text)
        if not match:
            return []
        sql = """
            SELECT m.*, bm25(memories_fts, 1.0, 0.4, 0.6) AS rank
            FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid
            WHERE memories_fts MATCH ?
        """
        params: list[Any] = [match]
        if category:
            sql += " AND m.category = ?"
            params.append(category)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self.db.query(sql, params)
        # bm25 é negativo (menor = melhor); combinamos com a importância.
        rows.sort(key=lambda r: r["rank"] - 0.35 * r["importance"])
        return rows

    def pinned(self, limit: int = 10) -> list[Memory]:
        rows = self.db.query(
            "SELECT * FROM memories WHERE pinned = 1 ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (limit,),
        )
        return [Memory.from_row(r) for r in rows]

    def relevant_for(self, text: str, *, limit: int = 6, pinned_limit: int = 8) -> list[Memory]:
        """Memórias para o contexto de um turno: fixadas + mais relevantes ao texto."""
        chosen: dict[int, Memory] = {m.id: m for m in self.pinned(pinned_limit)}
        for memory in self.search(text, limit=limit):
            chosen.setdefault(memory.id, memory)
        return list(chosen.values())

    def find_duplicate(self, content: str) -> Memory | None:
        target = normalize(content)
        if not target:
            return None
        for row in self._lexical(content, None, 10):  # texto igual sempre casa nas palavras
            if normalize(row["content"]) == target:
                return Memory.from_row(row)
        return None

    def stats(self) -> dict[str, Any]:
        rows = self.db.query("SELECT category, COUNT(*) AS total FROM memories GROUP BY category ORDER BY total DESC")
        total = sum(r["total"] for r in rows)
        return {"total": total, "by_category": {r["category"]: r["total"] for r in rows}}

    def _touch(self, ids: list[int]) -> None:
        marks = ",".join("?" for _ in ids)
        self.db.execute(
            f"UPDATE memories SET last_accessed_at = ?, access_count = access_count + 1 WHERE id IN ({marks})",
            [utcnow(), *ids],
        )

    # --- Exportação / importação ------------------------------------------
    def export(self) -> dict[str, Any]:
        rows = self.db.query("SELECT * FROM memories ORDER BY id")
        return {
            "format": "sexta-feira.memories",
            "version": 1,
            "exported_at": utcnow(),
            "memories": [Memory.from_row(r).to_dict() for r in rows],
        }

    def import_(self, payload: dict[str, Any] | str) -> dict[str, int]:
        data = json.loads(payload) if isinstance(payload, str) else payload
        items = data.get("memories") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("Arquivo inválido: lista 'memories' não encontrada.")
        created = updated = skipped = 0
        for item in items:
            if not isinstance(item, dict) or not str(item.get("content", "")).strip():
                skipped += 1
                continue
            _, was_created = self.add(
                str(item["content"]),
                category=item.get("category", "geral"),
                tags=item.get("tags"),
                importance=item.get("importance", 3),
                pinned=bool(item.get("pinned", False)),
                source="import",
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return {"created": created, "updated": updated, "skipped": skipped}
