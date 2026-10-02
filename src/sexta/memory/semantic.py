"""Memória semântica: busca por significado, não só por palavras.

Cada memória vira um vetor (embedding) de 384 números calculado **no seu computador**
pelo modelo multilíngue ``paraphrase-multilingual-MiniLM-L12-v2`` (via ``fastembed``,
ONNX, ~220 MB). Frases com sentido parecido ficam com vetores próximos, então
"tenho um automóvel elétrico" é encontrada ao perguntar sobre "carro".

A busca final é **híbrida**: o resultado do BM25 (palavras) e o da similaridade de
cosseno (significado) são combinados por *Reciprocal Rank Fusion* — cada lista vota
com 1/(60 + posição). É simples, robusto e não exige calibrar escalas diferentes.

Sem o pacote opcional (``pip install -e ".[memoria]"``) ou sem o modelo baixado, tudo
continua funcionando só com o BM25.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .db import Database, utcnow

log = logging.getLogger(__name__)

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MIN_SIMILARITY = 0.5  # abaixo disso, um resultado só-semântico costuma ser ruído
DUPLICATE_SIMILARITY = 0.9
RRF_K = 60


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> np.ndarray:
        """Matriz (n, dim) float32 com linhas normalizadas (norma 1)."""
        ...


class SemanticUnavailable(RuntimeError):
    pass


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix[None, :]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class FastEmbedEmbedder:
    """Embeddings locais com fastembed (ONNX Runtime, CPU)."""

    def __init__(self, cache_dir: Path, model: str = EMBED_MODEL):
        self.model = model
        self.cache_dir = Path(cache_dir)
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise SemanticUnavailable(
                'Busca semântica desativada: instale o pacote opcional com  pip install -e ".[memoria]"'
            ) from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._model = TextEmbedding(model_name=model, cache_dir=str(self.cache_dir))
        except Exception as exc:  # noqa: BLE001 — download/arquivo corrompido
            raise SemanticUnavailable(
                f"Não consegui carregar o modelo de embeddings ({type(exc).__name__}: {exc}). "
                "Verifique a internet e rode: sexta memoria instalar"
            ) from exc

    def embed(self, texts: list[str]) -> np.ndarray:
        return normalize_rows(np.array(list(self._model.embed(texts)), dtype=np.float32))


def rrf_merge(*rankings: list[int], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion: soma 1/(k + posição) de cada lista."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position + 1)
    return scores


class SemanticIndex:
    """Vetores das memórias (tabela ``memory_vectors``) + busca por similaridade.

    Estados: ``off`` (não iniciado), ``loading``, ``ready``, ``unavailable`` (falta pacote
    ou modelo) e ``disabled`` (desligado nas configurações).
    """

    def __init__(
        self,
        db: Database,
        factory: Callable[[], Embedder] | None,
        *,
        enabled: Callable[[], bool] = lambda: True,
    ):
        self.db = db
        self.factory = factory
        self.enabled = enabled
        self.embedder: Embedder | None = None
        self.state = "off"
        self.error: str | None = None
        self._lock = threading.RLock()
        self._cache: tuple[np.ndarray, np.ndarray] | None = None  # (ids, matriz)
        self._thread: threading.Thread | None = None

    # --- Ciclo de vida ----------------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self.state == "ready" and self.embedder is not None and self.enabled()

    def start(self, *, background: bool = True) -> None:
        """Carrega o modelo (pode baixar na primeira vez) e indexa o que faltar."""
        if self.factory is None or self.state == "loading":
            return
        if not self.enabled():
            self.state = "disabled"
            return
        self.state, self.error = "loading", None
        if background:
            self._thread = threading.Thread(target=self._load, name="sexta-embeddings", daemon=True)
            self._thread.start()
        else:
            self._load()

    def _load(self) -> None:
        try:
            embedder = self.factory() if self.factory else None
            if embedder is None:
                raise SemanticUnavailable("sem gerador de embeddings")
            with self._lock:
                self.embedder = embedder
                self.state = "ready"
            count = self.backfill()
            if count:
                log.info("Memória semântica: %s memória(s) indexada(s).", count)
        except SemanticUnavailable as exc:
            self.state, self.error = "unavailable", str(exc)
            log.info("%s", exc)
        except Exception as exc:  # noqa: BLE001
            self.state, self.error = "unavailable", f"{type(exc).__name__}: {exc}"
            log.exception("Falha ao iniciar a memória semântica")

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # --- Escrita ------------------------------------------------------------------------
    def index(self, memory_id: int, text: str) -> bool:
        if not self.ready:
            return False  # o backfill da próxima inicialização cobre o que faltar
        try:
            vector = self._embed([text])[0]
        except Exception as exc:  # noqa: BLE001 — falha aqui nunca impede salvar a memória
            log.warning("Embedding falhou para a memória %s: %s", memory_id, exc)
            return False
        self._store([(memory_id, vector)])
        return True

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def backfill(self, *, batch: int = 64, rebuild: bool = False) -> int:
        """Gera vetores das memórias sem vetor (ou de outro modelo). Retorna quantas indexou."""
        if self.embedder is None:
            return 0
        if rebuild:
            self.db.execute("DELETE FROM memory_vectors")
            self.invalidate()
        total = 0
        while True:
            rows = self.db.query(
                """SELECT m.id, m.content FROM memories m
                   LEFT JOIN memory_vectors v ON v.memory_id = m.id
                   WHERE v.memory_id IS NULL OR v.model != ?
                   ORDER BY m.id LIMIT ?""",
                (self.embedder.model, batch),
            )
            if not rows:
                return total
            vectors = self._embed([r["content"] for r in rows])
            self._store([(r["id"], v) for r, v in zip(rows, vectors, strict=True)])
            total += len(rows)

    def _embed(self, texts: list[str]) -> np.ndarray:
        assert self.embedder is not None
        with self._lock:
            return normalize_rows(self.embedder.embed(texts))

    def _store(self, items: list[tuple[int, np.ndarray]]) -> None:
        assert self.embedder is not None
        now = utcnow()
        for memory_id, vector in items:
            vec = np.asarray(vector, dtype=np.float32)
            self.db.execute(
                """INSERT INTO memory_vectors (memory_id, model, dim, vector, updated_at)
                   SELECT ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM memories WHERE id = ?)
                   ON CONFLICT(memory_id) DO UPDATE SET model = excluded.model, dim = excluded.dim,
                       vector = excluded.vector, updated_at = excluded.updated_at""",
                (memory_id, self.embedder.model, int(vec.shape[0]), vec.tobytes(), now, memory_id),
            )
        self.invalidate()

    # --- Leitura -----------------------------------------------------------------------
    def _matrix(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if self._cache is None:
                assert self.embedder is not None
                rows = self.db.query(
                    "SELECT memory_id, dim, vector FROM memory_vectors WHERE model = ? ORDER BY memory_id",
                    (self.embedder.model,),
                )
                if rows:
                    ids = np.array([r["memory_id"] for r in rows], dtype=np.int64)
                    matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32, count=r["dim"]) for r in rows])
                else:
                    ids, matrix = np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32)
                self._cache = (ids, matrix)
            return self._cache

    def search(self, text: str, *, limit: int = 20, min_similarity: float = MIN_SIMILARITY) -> list[tuple[int, float]]:
        """[(id_da_memória, similaridade)] em ordem decrescente."""
        if not self.ready or not text.strip():
            return []
        ids, matrix = self._matrix()
        if not len(ids):
            return []
        try:
            query = self._embed([text])[0]
        except Exception as exc:  # noqa: BLE001
            log.warning("Embedding da busca falhou: %s", exc)
            return []
        scores = matrix @ query
        order = np.argsort(-scores)[:limit]
        return [(int(ids[i]), float(scores[i])) for i in order if scores[i] >= min_similarity]

    def duplicates(self, *, threshold: float = DUPLICATE_SIMILARITY, limit: int = 50) -> list[tuple[int, int, float]]:
        """Pares de memórias muito parecidas (candidatas a mesclar). Calculado em blocos."""
        if not self.ready:
            return []
        ids, matrix = self._matrix()
        pairs: list[tuple[int, int, float]] = []
        block = 512
        for start in range(0, len(ids), block):
            sims = matrix[start : start + block] @ matrix.T
            for local, row in enumerate(sims):
                i = start + local
                for j in np.nonzero(row[i + 1 :] >= threshold)[0]:
                    pairs.append((int(ids[i]), int(ids[i + 1 + j]), float(row[i + 1 + j])))
        pairs.sort(key=lambda p: -p[2])
        return pairs[:limit]

    def status(self) -> dict[str, Any]:
        total = self.db.query_one("SELECT COUNT(*) AS n FROM memories")["n"]
        model = self.embedder.model if self.embedder else EMBED_MODEL
        indexed = self.db.query_one("SELECT COUNT(*) AS n FROM memory_vectors WHERE model = ?", (model,))["n"]
        state = "disabled" if not self.enabled() else self.state
        return {"state": state, "model": model, "indexed": indexed, "total": total, "error": self.error}
