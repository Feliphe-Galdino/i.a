"""Microfone e sinais sonoros (sounddevice / PortAudio).

No Windows, o pacote ``sounddevice`` já traz o PortAudio embutido: nada mais a instalar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

from .dsp import SAMPLE_RATE, resample_to_16k, to_int16

log = logging.getLogger(__name__)

FRAME_SAMPLES = 320  # 20 ms a 16 kHz


class VoiceDependencyError(RuntimeError):
    """Recurso de voz indisponível (pacote não instalado, sem microfone etc.)."""


def _sounddevice():
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise VoiceDependencyError(
            'Captura de áudio indisponível. Instale os recursos de voz: pip install -e ".[voz]"'
        ) from exc
    return sd


def list_input_devices() -> list[dict[str, Any]]:
    sd = _sounddevice()
    default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) > 0:
            hostapi = sd.query_hostapis(info["hostapi"])["name"]
            devices.append(
                {
                    "index": index,
                    "name": info["name"],
                    "hostapi": hostapi,
                    "default": index == default_in,
                    "samplerate": int(info.get("default_samplerate") or 0),
                }
            )
    return devices


def resolve_device(name: str) -> int | None:
    """Encontra o dispositivo pelo nome (ou parte dele). Vazio = padrão do Windows."""
    if not name:
        return None
    for dev in list_input_devices():
        if name.lower() in dev["name"].lower():
            return dev["index"]
    return None


class MicrophoneInput:
    """Captura contínua do microfone, entregando quadros int16 mono de 16 kHz (20 ms)."""

    def __init__(self, device: str = ""):
        self.device_name = device
        self._stream: Any = None
        self.samplerate = SAMPLE_RATE
        self.device_label = "padrão do sistema"

    def start(self, on_frame: Callable[[np.ndarray], None]) -> None:
        sd = _sounddevice()
        device = resolve_device(self.device_name)
        try:
            info = sd.query_devices(device, "input")
        except Exception as exc:  # noqa: BLE001
            raise VoiceDependencyError(f"Nenhum microfone encontrado ({exc}).") from exc
        self.device_label = info["name"]

        def callback(indata, _frames, _time, _status):
            mono = indata[:, 0] if indata.ndim > 1 else indata
            if self.samplerate != SAMPLE_RATE:
                mono = resample_to_16k(mono.astype(np.float32), self.samplerate)
            on_frame(to_int16(mono.copy()))

        # Tenta 16 kHz direto; se o driver recusar, usa a taxa nativa e reamostra.
        for rate in (SAMPLE_RATE, int(info.get("default_samplerate") or 48_000)):
            try:
                self.samplerate = rate
                block = int(rate * FRAME_SAMPLES / SAMPLE_RATE)
                self._stream = sd.InputStream(
                    samplerate=rate, channels=1, dtype="float32", blocksize=block, device=device, callback=callback
                )
                self._stream.start()
                log.info("Microfone: %s (%s Hz)", self.device_label, rate)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao abrir o microfone a %s Hz: %s", rate, exc)
                self._stream = None
        raise VoiceDependencyError("Não consegui abrir o microfone. Verifique se ele está conectado e liberado.")

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None


class Tones:
    """Bipes curtos de feedback (ativação, ok, desativação)."""

    NOTES = {"on": (660, 990), "ok": (880,), "off": (660, 440), "error": (330, 220)}

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @staticmethod
    def render(kind: str, rate: int = 22_050) -> np.ndarray:
        parts = []
        for freq in Tones.NOTES.get(kind, (880,)):
            t = np.arange(int(rate * 0.12)) / rate
            envelope = np.minimum(1.0, t / 0.01) * np.exp(-t / 0.04)
            parts.append(0.25 * np.sin(2 * np.pi * freq * t) * envelope)
            parts.append(np.zeros(int(rate * 0.02)))
        return np.concatenate(parts).astype(np.float32)

    def play(self, kind: str) -> None:
        if not self.enabled:
            return
        try:
            sd = _sounddevice()
            sd.play(self.render(kind), 22_050, blocking=False)
        except Exception as exc:  # noqa: BLE001 — bipe é opcional
            log.debug("Bipe indisponível: %s", exc)
