"""Rotas da voz local (motor no PC)."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..container import Sexta
from ..voice.audio import VoiceDependencyError, list_input_devices
from ..voice.tts import build_speaker
from .deps import get_sexta, require_token

router = APIRouter(prefix="/api/voice", dependencies=[Depends(require_token)])


@router.get("/status")
def voice_status(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    return sexta.voice.status()


@router.post("/activate")
def voice_activate(sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    return {"ok": sexta.voice.activate("botão")}


@router.post("/stop")
def voice_stop(sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    sexta.voice.stop_speaking()
    return {"ok": True}


class SayIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/say")
def voice_say(body: SayIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    if sexta.voice.state not in ("idle", "thinking", "speaking"):
        raise HTTPException(409, "A voz local não está ativa.")
    sexta.voice.say(body.text)
    return {"ok": True}


@router.get("/devices")
def voice_devices() -> list[dict[str, Any]]:
    try:
        return list_input_devices()
    except VoiceDependencyError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/voices")
def voice_voices(sexta: Sexta = Depends(get_sexta)) -> list[str]:
    speaker = sexta.voice._speaker or build_speaker()  # noqa: SLF001
    try:
        return speaker.voices()
    finally:
        if speaker is not sexta.voice._speaker:  # noqa: SLF001
            speaker.close()


@router.post("/models/download")
def voice_download(sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    size = sexta.runtime.get().voice_whisper_model

    def run() -> None:
        try:
            sexta.models.download_vosk(sexta.voice._progress)  # noqa: SLF001
            sexta.models.download_whisper(size, sexta.voice._progress)  # noqa: SLF001
            sexta.voice._publish({"type": "voice_download", "model": "todos", "progress": 1.0, "done": True})  # noqa: SLF001
            if sexta.voice.state in ("error", "off") and sexta.runtime.get().voice_engine == "local":
                sexta.voice.reconfigure()
        except Exception as exc:  # noqa: BLE001
            sexta.voice._publish({"type": "voice_download", "error": str(exc)})  # noqa: SLF001

    threading.Thread(target=run, name="sexta-model-download", daemon=True).start()
    return {"started": True}


@router.post("/restart")
def voice_restart(sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    sexta.voice.reconfigure()
    return {"ok": True}
