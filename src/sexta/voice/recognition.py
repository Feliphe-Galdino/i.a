"""Reconhecimento de fala local (offline).

* ``VoskSpotter``: escuta contínua barata, com gramática restrita às frases de ativação e de
  controle — por isso quase não confunde conversas normais com "Olá, Sexta-Feira".
* ``WhisperTranscriber``: transcreve o pedido completo em português (faster-whisper).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from .audio import VoiceDependencyError
from .text import match_control, match_wake, normalize_speech

log = logging.getLogger(__name__)

GRAMMAR = [
    "olá sexta feira",
    "oi sexta feira",
    "ei sexta feira",
    "bom dia sexta feira",
    "boa tarde sexta feira",
    "boa noite sexta feira",
    "sexta feira",
    "silêncio",
    "parar",
    "chega",
    "[unk]",
]

# Frases que o Whisper costuma "inventar" em trechos de silêncio/ruído.
HALLUCINATIONS = {
    "obrigado",
    "obrigada",
    "obrigado por assistir",
    "legendas pela comunidade amara org",
    "inscreva se no canal",
    "tchau",
    "tchau tchau",
    "e ai",
    "musica",
    "aplausos",
}


class VoskSpotter:
    def __init__(self, model_path: Path, *, sample_rate: int = 16_000, name_only: bool = False):
        try:
            import vosk  # type: ignore[import-not-found]
        except ImportError as exc:
            raise VoiceDependencyError('Vosk não instalado: pip install -e ".[voz]"') from exc
        vosk.SetLogLevel(-1)
        self._model = vosk.Model(str(model_path))
        self._rec = vosk.KaldiRecognizer(self._model, sample_rate, json.dumps(GRAMMAR, ensure_ascii=False))
        self.name_only = name_only

    def feed(self, frame: np.ndarray) -> str | None:
        """Retorna "wake", "silence", "stop" ou None."""
        if self._rec.AcceptWaveform(frame.astype(np.int16).tobytes()):
            text = json.loads(self._rec.Result()).get("text", "")
            final = True
        else:
            text = json.loads(self._rec.PartialResult()).get("partial", "")
            final = False
        return classify_spotted(text, final=final, name_only=self.name_only, reset=self.reset)

    def reset(self) -> None:
        self._rec.Reset()


def classify_spotted(text: str, *, final: bool, name_only: bool, reset=None) -> str | None:
    clean = " ".join(w for w in (text or "").split() if w != "[unk]")
    if not clean:
        return None
    if match_wake(clean, name_only=name_only) is not None:
        if reset:
            reset()
        return "wake"
    if final:
        control = match_control(clean)
        if control in ("silence", "stop"):
            return control
    return None


class WhisperTranscriber:
    def __init__(self, model_dir: Path, *, compute_type: str = "int8", cpu_threads: int = 0):
        self.model_dir = model_dir
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            except ImportError as exc:
                raise VoiceDependencyError('faster-whisper não instalado: pip install -e ".[voz]"') from exc
            self._model = WhisperModel(
                str(self.model_dir), device="cpu", compute_type=self.compute_type, cpu_threads=self.cpu_threads
            )
            log.info("Modelo Whisper carregado de %s", self.model_dir)

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        segments, _info = self._model.transcribe(  # type: ignore[union-attr]
            audio.astype(np.float32),
            language="pt",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=True,
            hotwords="Sexta-Feira",
        )
        return clean_transcript(" ".join(segment.text.strip() for segment in segments))


def clean_transcript(text: str) -> str:
    text = " ".join((text or "").split())
    if normalize_speech(text) in HALLUCINATIONS:
        return ""
    return text
