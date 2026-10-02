"""Processamento de áudio local: palmas, detecção de fala (fim do pedido) e buffer circular.

Tudo em NumPy, sem enviar áudio para lugar nenhum. O detector de palmas é o mesmo
algoritmo da versão JavaScript (``web/js/voice/clap-detector.js``).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000


def to_float(frame: np.ndarray) -> np.ndarray:
    """int16 → float32 em [-1, 1]."""
    if frame.dtype == np.int16:
        return frame.astype(np.float32) / 32768.0
    return frame.astype(np.float32, copy=False)


def to_int16(frame: np.ndarray) -> np.ndarray:
    if frame.dtype == np.int16:
        return frame
    return (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)


def resample_to_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    """Reamostra para 16 kHz (média por blocos para múltiplos inteiros; interpolação no resto)."""
    if rate == SAMPLE_RATE:
        return audio
    if rate % SAMPLE_RATE == 0:
        factor = rate // SAMPLE_RATE
        usable = len(audio) - len(audio) % factor
        return audio[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)
    target = int(round(len(audio) * SAMPLE_RATE / rate))
    positions = np.linspace(0, len(audio) - 1, target)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) if len(frame) else 0.0


class ClapDetector:
    """Duas palmas (sons impulsivos, curtos, bem acima do ambiente) = ativação."""

    def __init__(self, *, sample_rate: int = SAMPLE_RATE, sensitivity: float = 0.5, level_every_s: float = 0.2):
        self.sample_rate = sample_rate
        self.set_sensitivity(sensitivity)
        self.t = 0.0
        self.floor = 0.003
        self.recent = 0.003
        self.state = "idle"
        self.onset_t = 0.0
        self.max_rms = 0.0
        self.sustained = False
        self.last_clap_t = -math.inf
        self.lock_until = 0.0
        self.refractory_until = 0.0
        self.level_every = level_every_s
        self.next_level_t = 0.0
        self.level_peak = 0.0
        self.min_gap = 0.12
        self.max_gap = 0.9
        self.max_clap_duration = 0.15

    def set_sensitivity(self, value: float) -> None:
        s = min(1.0, max(0.0, float(value)))
        self.sensitivity = s
        self.peak_threshold = 0.45 - 0.37 * s
        self.ratio = 14 - 9 * s

    def process(self, frame: np.ndarray) -> list[dict]:
        if not len(frame):
            return []
        samples = to_float(frame)
        peak = float(np.max(np.abs(samples)))
        level = rms(samples)
        t = self.t
        self.t += len(samples) / self.sample_rate
        events: list[dict] = []

        self.level_peak = max(self.level_peak, peak)
        if t >= self.next_level_t:
            events.append(
                {"type": "level", "peak": self.level_peak, "floor": self.floor, "threshold": self.peak_threshold}
            )
            self.level_peak = 0.0
            self.next_level_t = t + self.level_every

        if self.state == "idle":
            reference = max(self.floor, self.recent)
            if t >= self.refractory_until and peak >= self.peak_threshold and level >= reference * self.ratio:
                self.state = "event"
                self.onset_t = t
                self.max_rms = level
                self.sustained = False
            elif level < self.floor * 3:
                self.floor = max(0.0015, self.floor * 0.98 + level * 0.02)
        else:
            self.max_rms = max(self.max_rms, level)
            duration = t - self.onset_t
            if level < self.max_rms * 0.2 or level < self.floor * 2:
                self.state = "idle"
                self.refractory_until = t + 0.06
                if not self.sustained and duration <= self.max_clap_duration:
                    events.extend(self._register(self.onset_t))
            elif duration > self.max_clap_duration:
                self.sustained = True
        self.recent = self.recent * 0.97 + level * 0.03
        return events

    def _register(self, at: float) -> list[dict]:
        if at < self.lock_until:
            return []
        out = [{"type": "clap", "t": at}]
        gap = at - self.last_clap_t
        if self.min_gap <= gap <= self.max_gap:
            out.append({"type": "double", "t": at})
            self.last_clap_t = -math.inf
            self.lock_until = at + 1.2
        else:
            self.last_clap_t = at
        return out


@dataclass
class EndpointResult:
    status: str  # "waiting" | "speaking" | "done" | "timeout"


class Endpointer:
    """Grava o pedido falado e detecta quando a pessoa terminou de falar (silêncio)."""

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        noise_floor: float = 0.004,
        start_timeout: float = 6.0,
        end_silence: float = 0.9,
        min_speech: float = 0.25,
        max_duration: float = 15.0,
        preroll: np.ndarray | None = None,
        already_speaking: bool = False,
        ignore_s: float = 0.0,
    ):
        self.sample_rate = sample_rate
        self.threshold = max(noise_floor * 3.5, 0.012)
        self.start_timeout = start_timeout
        self.end_silence = end_silence
        self.min_speech = min_speech
        self.max_duration = max_duration
        self.chunks: list[np.ndarray] = [to_float(preroll)] if preroll is not None and len(preroll) else []
        self.elapsed = 0.0
        self.speech_time = min_speech if already_speaking else 0.0
        self.silence_time = 0.0
        self.started = already_speaking
        self.status = "speaking" if already_speaking else "waiting"
        self.ignore_s = ignore_s  # período inicial ignorado pelo detector (o bipe de ativação)

    def feed(self, frame: np.ndarray) -> str:
        if self.status in ("done", "timeout"):
            return self.status
        samples = to_float(frame)
        dt = len(samples) / self.sample_rate
        self.elapsed += dt
        if self.ignore_s > 0:
            self.ignore_s -= dt
            if self.started:
                self.chunks.append(samples)
            return self.status
        voiced = rms(samples) >= self.threshold
        if self.started:
            self.chunks.append(samples)
            if voiced:
                self.speech_time += dt
                self.silence_time = 0.0
            else:
                self.silence_time += dt
            if (
                self.speech_time >= self.min_speech
                and self.silence_time >= self.end_silence
                or self.elapsed >= self.max_duration
            ):
                self.status = "done"
        else:
            if voiced:
                self.started = True
                self.status = "speaking"
                self.chunks.append(samples)
                self.speech_time += dt
            elif self.elapsed >= self.start_timeout:
                self.status = "timeout"
        return self.status

    def audio(self) -> np.ndarray:
        return np.concatenate(self.chunks).astype(np.float32) if self.chunks else np.zeros(0, dtype=np.float32)


class RingBuffer:
    """Guarda os últimos N segundos de áudio (para não perder o começo do pedido)."""

    def __init__(self, seconds: float = 4.0, sample_rate: int = SAMPLE_RATE):
        self.max_samples = int(seconds * sample_rate)
        self.sample_rate = sample_rate
        self._chunks: deque[np.ndarray] = deque()
        self._size = 0

    def append(self, frame: np.ndarray) -> None:
        samples = to_float(frame)
        self._chunks.append(samples)
        self._size += len(samples)
        while self._size - len(self._chunks[0]) >= self.max_samples:
            self._size -= len(self._chunks.popleft())

    def last(self, seconds: float) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._chunks)
        return audio[-int(seconds * self.sample_rate) :]

    def clear(self) -> None:
        self._chunks.clear()
        self._size = 0
