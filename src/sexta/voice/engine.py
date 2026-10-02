"""Motor de voz local — a Sexta-Feira ouvindo e falando direto do seu computador.

Fluxo:

    microfone (20 ms) ─┬─▶ palmas (local) ──────────────┐
                       ├─▶ "Olá, Sexta-Feira" (Vosk) ────┤ ativação + bipe
                       └─▶ buffer dos últimos 4 s        │
                                                         ▼
                      grava o pedido até você parar de falar (silêncio)
                                                         ▼
                      transcreve offline (faster-whisper) ▶ orquestrador (canal "voz")
                                                         ▼
                      resposta pronta (evento task_done) ▶ fala pelo Windows (SAPI)

Threads: o áudio chega numa thread do driver, é processado numa thread própria, a
transcrição roda em outra (para não perder áudio) e a fala na thread do SAPI. O contato
com o núcleo assíncrono é feito com ``run_coroutine_threadsafe``/``call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from .audio import MicrophoneInput, Tones, VoiceDependencyError
from .dsp import ClapDetector, Endpointer, RingBuffer
from .models import ModelStore
from .recognition import VoskSpotter, WhisperTranscriber
from .text import match_control, match_wake, normalize_speech, shorten_paths, to_speakable
from .tts import build_speaker

log = logging.getLogger(__name__)

CONVERSATION_IDLE_S = 30 * 60  # depois de 30 min sem falar, começa uma conversa nova
ACTIVE_STATES = ("idle", "listening", "transcribing", "thinking", "speaking")


class VoiceEngine:
    def __init__(
        self,
        *,
        runtime: Any,
        orchestrator: Any,
        bus: Any,
        approvals: Any,
        tasks: Any,
        models: ModelStore,
        mic_factory: Callable[[str], Any] = MicrophoneInput,
        spotter_factory: Callable[..., Any] = VoskSpotter,
        transcriber_factory: Callable[..., Any] = WhisperTranscriber,
        speaker_factory: Callable[..., Any] = build_speaker,
        tones: Tones | None = None,
        auto_download: bool = True,
    ):
        self.runtime = runtime
        self.orchestrator = orchestrator
        self.bus = bus
        self.approvals = approvals
        self.tasks = tasks
        self.models = models
        self.mic_factory = mic_factory
        self.spotter_factory = spotter_factory
        self.transcriber_factory = transcriber_factory
        self.speaker_factory = speaker_factory
        self.tones = tones or Tones()
        self.auto_download = auto_download

        self.state = "off"
        self.detail = ""
        self.error = ""
        self.transcript = ""
        self.device = ""
        self.loop: asyncio.AbstractEventLoop | None = None
        self.conversation_id: str | None = None

        self._lock = threading.RLock()
        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=600)
        self._running = threading.Event()
        self._generation = 0
        self._worker: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="sexta-stt")
        self._events_task: asyncio.Task | None = None
        self._mic: Any = None
        self._spotter: Any = None
        self._transcriber: Any = None
        self._speaker: Any = None
        self._clap = ClapDetector()
        self._ring = RingBuffer(4.0)
        self._claps_enabled = True
        self._endpointer: Endpointer | None = None
        self._listen_source = ""
        self._retried = False
        self._awaiting: dict[str, Any] | None = None
        self._approval_retries = 0
        self._voice_tasks: set[str] = set()
        self._last_interaction = 0.0
        self._speaking = 0
        self._pending_say: list[str] = []

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        if self._events_task is None:
            self._events_task = loop.create_task(self._event_loop())
        cfg = self.runtime.get()
        if cfg.voice_engine != "local":
            self._set_state("off", detail="")
            return
        self._generation += 1
        threading.Thread(target=self._boot, args=(self._generation,), name="sexta-voice-boot", daemon=True).start()

    def _boot(self, generation: int) -> None:
        cfg = self.runtime.get()
        self._set_state("starting", detail="Preparando a voz local…")
        try:
            size = cfg.voice_whisper_model
            try:
                if cfg.voice_wake and not self.models.vosk_ready():
                    if not self.auto_download:
                        raise VoiceDependencyError("Modelo de ativação não encontrado. Rode: sexta voz instalar")
                    self._set_state("starting", detail="Baixando o modelo de ativação (31 MB)…")
                    self.models.download_vosk(self._progress)
                if not self.models.whisper_ready(size):
                    if not self.auto_download:
                        raise VoiceDependencyError("Modelo de transcrição não encontrado. Rode: sexta voz instalar")
                    self._set_state("starting", detail=f"Baixando o modelo de transcrição ({size})…")
                    self.models.download_whisper(size, self._progress)
            except VoiceDependencyError:
                raise
            except ImportError as exc:
                raise VoiceDependencyError('Recursos de voz não instalados: pip install -e ".[voz]"') from exc
            except Exception as exc:  # noqa: BLE001 — rede, disco etc.
                raise VoiceDependencyError(
                    f"Não consegui baixar os modelos de voz ({exc}). Verifique a internet e use "
                    "“Baixar modelos” nas Configurações ou rode: sexta voz instalar"
                ) from exc
            if generation != self._generation:
                return
            self._speaker = self.speaker_factory(voice=cfg.voice_tts_voice, rate=cfg.voice_tts_rate)
            self._spotter = (
                self.spotter_factory(self.models.vosk_dir, name_only=cfg.voice_name_only) if cfg.voice_wake else None
            )
            self._set_state("starting", detail="Carregando o modelo de transcrição…")
            self._transcriber = self.transcriber_factory(self.models.whisper_dir(size))
            self._transcriber.load()
            self._clap.set_sensitivity(cfg.voice_clap_sensitivity)
            self._claps_enabled = cfg.voice_claps
            self._mic = self.mic_factory(cfg.voice_input_device)
            self._running.set()
            self._worker = threading.Thread(target=self._work, name="sexta-voice", daemon=True)
            self._worker.start()
            self._mic.start(self._on_audio)
            self.device = getattr(self._mic, "device_label", "")
            triggers = [t for t, on in (("“Olá, Sexta-Feira”", cfg.voice_wake), ("duas palmas", cfg.voice_claps)) if on]
            self._set_state(
                "idle", detail=f"Aguardando {' ou '.join(triggers) or 'o botão'} · microfone: {self.device}"
            )
        except VoiceDependencyError as exc:
            self._fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao iniciar a voz local")
            self._fail(f"Falha ao iniciar a voz local: {exc}")

    def stop(self) -> None:
        self._generation += 1
        self._running.clear()
        if self._mic is not None:
            self._mic.stop()
            self._mic = None
        if self._speaker is not None:
            self._speaker.close()
            self._speaker = None
        self._endpointer = None
        self._awaiting = None
        self._speaking = 0
        self._set_state("off", detail="")

    def reconfigure(self) -> None:
        self.stop()
        if self.loop is not None:
            self.start(self.loop)

    LIVE_KEYS = {
        "voice_tts_voice",
        "voice_tts_rate",
        "voice_mode",
        "voice_speak_alerts",
        "voice_clap_sensitivity",
        "voice_claps",
    }

    def apply_settings(self, changed: set[str]) -> None:
        """Aplica mudanças de configuração; só reinicia o motor quando necessário."""
        voice_keys = {k for k in changed if k.startswith("voice_")}
        if not voice_keys:
            return
        if voice_keys <= self.LIVE_KEYS and self.state in ACTIVE_STATES:
            cfg = self.runtime.get()
            if self._speaker is not None:
                self._speaker.configure(voice=cfg.voice_tts_voice, rate=cfg.voice_tts_rate)
            self._clap.set_sensitivity(cfg.voice_clap_sensitivity)
            self._claps_enabled = cfg.voice_claps
            return
        self.reconfigure()

    def shutdown(self) -> None:
        self.stop()
        if self._events_task is not None:
            self._events_task.cancel()
            self._events_task = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    def status(self) -> dict[str, Any]:
        cfg = self.runtime.get()
        return {
            "engine": cfg.voice_engine,
            "state": self.state,
            "detail": self.detail,
            "error": self.error,
            "device": self.device,
            "speaker": getattr(self._speaker, "name", ""),
            "models": self.models.status(cfg.voice_whisper_model),
        }

    # ------------------------------------------------------------------
    # Ações públicas (podem vir de qualquer thread)
    # ------------------------------------------------------------------
    def activate(self, source: str = "botão") -> bool:
        if self.state == "speaking":
            self.stop_speaking()
        if self.state in ("idle", "thinking"):
            self._begin_listening(source, preroll=False)
            return True
        return False

    def stop_speaking(self) -> None:
        if self._speaker is not None:
            self._speaker.stop()
        self._speaking = 0
        if self.state == "speaking":
            self._set_state("idle")

    def say(self, text: str, on_done: Callable[[], None] | None = None) -> None:
        spoken = to_speakable(text)
        if not spoken or self._speaker is None or self.state not in ACTIVE_STATES:
            if on_done:
                on_done()
            return
        if self.state in ("listening", "transcribing") and on_done is None:
            self._pending_say.append(spoken)  # não interrompe quem está falando com ela
            return
        with self._lock:
            self._speaking += 1
        self._set_state("speaking")
        if self._spotter is not None:
            self._spotter.reset()

        def finished() -> None:
            def later() -> None:
                time.sleep(0.35)  # evita ouvir o fim da própria fala
                with self._lock:
                    self._speaking = max(0, self._speaking - 1)
                    last = self._speaking == 0
                if last and self.state == "speaking":
                    self._set_state("idle")
                if on_done:
                    on_done()

            threading.Thread(target=later, daemon=True).start()

        self._speaker.say(spoken, on_done=finished)

    # ------------------------------------------------------------------
    # Áudio
    # ------------------------------------------------------------------
    def _on_audio(self, frame: np.ndarray) -> None:
        with contextlib.suppress(queue.Full):  # sobrecarga momentânea: descarta o quadro
            self._frames.put_nowait(frame)

    def _work(self) -> None:
        while self._running.is_set():
            try:
                frame = self._frames.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                self.process_frame(frame)
            except Exception:  # noqa: BLE001
                log.exception("Erro ao processar áudio")

    def process_frame(self, frame: np.ndarray) -> None:
        """Processa um quadro int16 de 16 kHz (público para testes)."""
        self._ring.append(frame)
        for event in self._clap.process(frame):
            if event["type"] == "level":
                self._publish({"type": "voice_level", "peak": event["peak"], "threshold": event["threshold"]})
            elif event["type"] == "clap":
                self._publish({"type": "voice_clap"})
            elif event["type"] == "double" and self._claps_enabled:
                self._on_double_clap()

        state = self.state
        if state in ("idle", "thinking") and self._spotter is not None:
            if self._spotter.feed(frame) == "wake":
                self._begin_listening("voz", preroll=True)
        elif state == "speaking" and self._spotter is not None:
            result = self._spotter.feed(frame)
            if result in ("silence", "stop"):
                self.stop_speaking()
                if result == "stop":
                    self._cancel_tasks()
        elif state == "listening" and self._endpointer is not None:
            status = self._endpointer.feed(frame)
            if status == "done":
                audio = self._endpointer.audio()
                self._endpointer = None
                self._set_state("transcribing", detail="Entendendo…")
                self._executor.submit(self._transcribe, audio, self._generation)
            elif status == "timeout":
                self._endpointer = None
                self._on_listen_timeout()

    def _on_double_clap(self) -> None:
        self._publish({"type": "voice_double_clap"})
        if self.state == "speaking":
            self.stop_speaking()
        elif self.state in ("idle", "thinking"):
            self._begin_listening("palmas", preroll=False)

    def _begin_listening(self, source: str, *, preroll: bool) -> None:
        with self._lock:
            self.tones.play("on")
            self._endpointer = Endpointer(
                noise_floor=self._clap.floor,
                preroll=self._ring.last(1.6) if preroll else None,
                already_speaking=preroll,
                start_timeout=10.0 if self._awaiting else 7.0,
                ignore_s=0.3,
            )
            self._listen_source = source
            if source != "continuação":
                self._retried = False
            self.transcript = ""
            if self._spotter is not None:
                self._spotter.reset()
        self._set_state("listening", detail="Diga “sim” ou “não”…" if self._awaiting else "Ouvindo…")

    def _on_listen_timeout(self) -> None:
        self.tones.play("off")
        self._set_state("idle")
        if self._awaiting:
            self._awaiting = None
            self.say("Sem resposta. A confirmação continua na tela.")

    # ------------------------------------------------------------------
    # Transcrição e comandos
    # ------------------------------------------------------------------
    def _transcribe(self, audio: np.ndarray, generation: int) -> None:
        try:
            text = self._transcriber.transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha na transcrição")
            self.tones.play("error")
            self._set_state("idle", detail=f"Falha na transcrição: {exc}")
            return
        if generation != self._generation:
            return
        self.transcript = text
        self._publish({"type": "voice_transcript", "text": text})
        if self._awaiting:
            self._approval_answer(text)
            return
        command = match_wake(text, name_only=True)
        command = (text if command is None else command).strip()
        if not command:
            if self._listen_source == "voz" and not self._retried:
                self._retried = True
                self._begin_listening("continuação", preroll=False)  # falou só "Olá, Sexta-Feira"
                return
            self.tones.play("off")
            self._set_state("idle")
            return
        self.handle_command(command)

    def handle_command(self, command: str) -> None:
        control = match_control(command)
        if control == "silence":
            self._set_state("idle")
            return
        if control == "stop" or (control == "no" and normalize_speech(command).startswith("cancel")):
            count = self._cancel_tasks()
            self._set_state("idle")
            self.say("Certo, interrompi." if count else "Não há nada em andamento.")
            return
        self.tones.play("ok")
        self._set_state("thinking", detail=command)
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._submit(command), self.loop)

    async def _submit(self, command: str) -> None:
        conversation = None
        recent = time.monotonic() - self._last_interaction < CONVERSATION_IDLE_S
        if self.conversation_id and recent and self.orchestrator.conversations.get(self.conversation_id):
            conversation = self.conversation_id
        try:
            ids = await self.orchestrator.submit(command, conversation_id=conversation, channel="voz")
        except Exception as exc:  # noqa: BLE001
            self._set_state("idle")
            self.say(f"Não consegui enviar o pedido. {exc}")
            return
        self.conversation_id = ids["conversation_id"]
        self._last_interaction = time.monotonic()
        self._voice_tasks.add(ids["task_id"])
        await self.bus.publish({"type": "voice_command", "text": command, **ids})

    def _cancel_tasks(self) -> int:
        count = len(self.tasks.running_ids())
        if self.loop is not None and count:
            self.loop.call_soon_threadsafe(self.tasks.cancel_all)
        return count

    # ------------------------------------------------------------------
    # Eventos do núcleo: respostas, confirmações e alertas
    # ------------------------------------------------------------------
    async def _event_loop(self) -> None:
        queue_ = self.bus.subscribe()
        try:
            while True:
                event = await queue_.get()
                try:
                    self.on_event(event)
                except Exception:  # noqa: BLE001
                    log.exception("Erro tratando evento na voz")
        finally:
            self.bus.unsubscribe(queue_)

    def on_event(self, event: dict[str, Any]) -> None:
        if self.state not in ACTIVE_STATES:
            return
        kind = event.get("type")
        cfg = self.runtime.get()
        if kind == "task_done":
            task_id = event.get("task_id")
            by_voice = event.get("channel") == "voz" or task_id in self._voice_tasks
            self._voice_tasks.discard(task_id)
            if by_voice or cfg.voice_mode == "voz":
                status = event.get("status")
                if status in ("done", "refused"):
                    text = event.get("text") or "Pronto."
                elif status == "cancelled":
                    text = "Tarefa interrompida."
                elif status == "blocked":
                    text = "O orçamento diário foi atingido. Ajuste nas configurações."
                else:
                    text = f"Não consegui concluir. {event.get('error') or ''}"
                self.say(text)
            elif self.state == "thinking" and not self._voice_tasks:
                self._set_state("idle")
        elif kind == "approval_required":
            self._on_approval(event)
        elif kind == "approval_resolved":
            if self._awaiting and self._awaiting.get("approval_id") == event.get("approval_id"):
                self._awaiting = None
                if self.state == "listening":
                    self._endpointer = None
                    self._set_state("idle")
        elif kind == "alert" and cfg.voice_speak_alerts:
            self.say(f"Alerta: {event.get('title', '')}. {event.get('message', '')}")
        elif kind == "briefing_ready" and cfg.voice_speak_alerts:
            self.say(f"Seu resumo está pronto. {event.get('headline', '')}")

    def _on_approval(self, event: dict[str, Any]) -> None:
        summary = shorten_paths(event.get("summary") or event.get("tool") or "")
        if event.get("risk") == "critical":
            self.say(f"Atenção: ação crítica. {summary}. Por segurança, confirme na tela.")
            return
        self._awaiting = event
        self._approval_retries = 0
        self.say(f"Preciso da sua confirmação: {summary}. Diga sim ou não.", on_done=self._listen_for_approval)

    def _listen_for_approval(self) -> None:
        if self._awaiting and self.state in ("idle", "thinking", "speaking"):
            self._begin_listening("aprovação", preroll=False)

    def _approval_answer(self, text: str) -> None:
        request = self._awaiting
        control = match_control(text)
        if request is None:
            return
        if control == "yes":
            self._awaiting = None
            self._resolve(request["approval_id"], True)
            self.tones.play("ok")
            self._set_state("thinking")
        elif control in ("no", "stop"):
            self._awaiting = None
            self._resolve(request["approval_id"], False)
            self._set_state("idle")
            self.say("Tudo bem, não vou fazer.")
        elif self._approval_retries < 1:
            self._approval_retries += 1
            self._set_state("idle")
            self.say("Não entendi. Diga sim ou não.", on_done=self._listen_for_approval)
        else:
            self._awaiting = None
            self._set_state("idle")
            self.say("Deixei a confirmação na tela.")

    def _resolve(self, approval_id: str, approved: bool) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.approvals.resolve, approval_id, approved)

    # ------------------------------------------------------------------
    # Estado e eventos
    # ------------------------------------------------------------------
    def _set_state(self, state: str, *, detail: str | None = None) -> None:
        with self._lock:
            self.state = state
            if detail is not None:
                self.detail = detail
            if state != "error":
                self.error = ""
        self._publish(
            {
                "type": "voice_state",
                "state": state,
                "detail": self.detail,
                "error": self.error,
                "transcript": self.transcript,
            }
        )
        if state in ("idle", "thinking") and self._pending_say:
            pending, self._pending_say = self._pending_say, []
            self.say(" ".join(pending))

    def _fail(self, message: str) -> None:
        log.warning("Voz local indisponível: %s", message)
        with self._lock:
            self.state = "error"
            self.error = message
            self.detail = ""
        self._running.clear()
        self._publish({"type": "voice_state", "state": "error", "detail": "", "error": message, "transcript": ""})

    def _progress(self, what: str, fraction: float) -> None:
        self._publish({"type": "voice_download", "model": what, "progress": round(fraction, 3)})

    def _publish(self, event: dict[str, Any]) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(self.bus.publish(event), loop)
