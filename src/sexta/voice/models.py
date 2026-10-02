"""Modelos locais de voz e linguagem (baixados uma vez, usados offline).

* Vosk pt (31 MB) — escuta contínua da frase "Olá, Sexta-Feira" (gramática restrita).
* faster-whisper (base ≈ 145 MB, small ≈ 470 MB…) — transcrição do pedido em português.
* Embeddings multilíngues (≈ 220 MB) — memória semântica (Fase 3).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

VOSK_NAME = "vosk-model-small-pt-0.3"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK_NAME}.zip"
WHISPER_SIZES = ("base", "small", "medium", "large-v3-turbo")

Progress = Callable[[str, float], None]


def safe_extract(zip_path: Path, target: Path) -> None:
    """Extrai um zip impedindo caminhos que escapem da pasta (zip slip)."""
    target = target.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (target / member.filename).resolve()
            if not destination.is_relative_to(target):
                raise ValueError(f"Arquivo suspeito no zip: {member.filename}")
        archive.extractall(target)


class ModelStore:
    def __init__(self, base: Path):
        self.base = base

    @property
    def vosk_dir(self) -> Path:
        return self.base / VOSK_NAME

    def whisper_dir(self, size: str) -> Path:
        return self.base / "whisper" / size

    @property
    def embeddings_dir(self) -> Path:
        return self.base / "embeddings"

    def vosk_ready(self) -> bool:
        return (self.vosk_dir / "am").is_dir() or (self.vosk_dir / "conf").is_dir()

    def whisper_ready(self, size: str) -> bool:
        return (self.whisper_dir(size) / "model.bin").is_file()

    def status(self, whisper_size: str) -> dict[str, object]:
        return {
            "vosk": self.vosk_ready(),
            "whisper": self.whisper_ready(whisper_size),
            "whisper_size": whisper_size,
            "path": str(self.base),
        }

    # --- Downloads ----------------------------------------------------------------
    def download_vosk(self, progress: Progress | None = None) -> Path:
        if self.vosk_ready():
            return self.vosk_dir
        import httpx

        self.base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.base) as tmp:
            zip_path = Path(tmp) / "vosk.zip"
            with httpx.stream("GET", VOSK_URL, follow_redirects=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with zip_path.open("wb") as fh:
                    for chunk in response.iter_bytes(1 << 16):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            progress("vosk", done / total)
            extract_dir = Path(tmp) / "x"
            safe_extract(zip_path, extract_dir)
            source = extract_dir / VOSK_NAME
            if not source.is_dir():
                source = next(p for p in extract_dir.iterdir() if p.is_dir())
            if self.vosk_dir.exists():
                shutil.rmtree(self.vosk_dir)
            shutil.move(str(source), str(self.vosk_dir))
        if progress:
            progress("vosk", 1.0)
        return self.vosk_dir

    def download_whisper(self, size: str, progress: Progress | None = None) -> Path:
        if self.whisper_ready(size):
            return self.whisper_dir(size)
        from faster_whisper import download_model  # type: ignore[import-not-found]

        if progress:
            progress(f"whisper-{size}", 0.0)
        target = self.whisper_dir(size)
        target.mkdir(parents=True, exist_ok=True)
        download_model(size, output_dir=str(target))
        if progress:
            progress(f"whisper-{size}", 1.0)
        return target
