"""Voz local: funções de texto, DSP e o motor completo com componentes simulados."""

from __future__ import annotations

import asyncio
import zipfile

import numpy as np
import pytest

from conftest import ScriptedProvider, text, tool_use
from sexta.container import build_sexta
from sexta.voice.audio import Tones
from sexta.voice.dsp import ClapDetector, Endpointer, RingBuffer, resample_to_16k
from sexta.voice.models import ModelStore, safe_extract
from sexta.voice.recognition import classify_spotted, clean_transcript
from sexta.voice.text import match_control, match_wake, shorten_paths, to_speakable
from sexta.voice.tts import NullSpeaker

RATE = 16_000
FRAME = 320  # 20 ms


def frames_of(signal: np.ndarray):
    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16)
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        yield pcm[i : i + FRAME]


def silence(seconds: float, noise: float = 0.002) -> np.ndarray:
    rng = np.random.default_rng(1)
    return (rng.uniform(-1, 1, int(seconds * RATE)) * noise).astype(np.float32)


def speech(seconds: float, amplitude: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def clap(amplitude: float = 0.8) -> np.ndarray:
    rng = np.random.default_rng(7)
    n = int(0.06 * RATE)
    return (rng.uniform(-1, 1, n) * amplitude * np.exp(-np.arange(n) / (0.008 * RATE))).astype(np.float32)


# --- Texto (mesmas regras da versão JavaScript) --------------------------------


def test_match_wake_variants_and_command():
    for phrase in ["Olá, Sexta-Feira", "olá sexta feira", "Oi Sexta-feira!", "bom dia sexta-feira", "olá 6ª feira"]:
        assert match_wake(phrase) == "", phrase
    assert match_wake("Olá, Sexta-Feira, que horas são?") == "que horas são?"
    assert match_wake("na sexta-feira eu vou ao cinema") is None
    assert match_wake("Sexta-Feira, abra o Chrome", name_only=True) == "abra o Chrome"


def test_match_control_and_text_helpers():
    assert match_control("Silêncio!") == "silence"
    assert match_control("parar") == "stop"
    assert match_control("sim, pode") == "yes"
    assert match_control("não") == "no"
    assert match_control("para que serve isso") is None
    assert shorten_paths("Substituir C:\\Users\\eu\\notas.md agora") == "Substituir notas.md agora"
    spoken = to_speakable("## Oi\n**Pronto!** Veja [aqui](https://x.com).\n```py\nprint(1)\n```")
    assert "#" not in spoken and "*" not in spoken and spoken.endswith("Coloquei o código na tela.")


def test_spotter_classification_and_hallucination_filter():
    assert classify_spotted("olá sexta feira", final=False, name_only=False) == "wake"
    assert classify_spotted("[unk] sexta feira [unk]", final=True, name_only=False) is None
    assert classify_spotted("silêncio", final=True, name_only=False) == "silence"
    assert classify_spotted("silêncio", final=False, name_only=False) is None
    assert clean_transcript("Obrigado.") == ""
    assert clean_transcript("  abra   o bloco de notas ") == "abra o bloco de notas"


# --- DSP -------------------------------------------------------------------------


def test_clap_detector_python_port():
    detector = ClapDetector()
    signal = np.concatenate([silence(1), clap(), silence(0.35), clap(), silence(1)])
    events = [e for f in frames_of(signal) for e in detector.process(f)]
    assert sum(e["type"] == "double" for e in events) == 1
    sustained = ClapDetector()
    events = [
        e for f in frames_of(np.concatenate([silence(1), speech(1, 0.5), silence(1)])) for e in sustained.process(f)
    ]
    assert not any(e["type"] == "double" for e in events)


def test_endpointer_detects_end_of_speech_and_timeout():
    ep = Endpointer()
    statuses = [ep.feed(f) for f in frames_of(np.concatenate([silence(0.5), speech(1.0), silence(1.2)]))]
    assert statuses[-1] == "done"
    assert 1.0 <= len(ep.audio()) / RATE <= 2.4
    waiting = Endpointer(start_timeout=1.0)
    assert [waiting.feed(f) for f in frames_of(silence(1.2))][-1] == "timeout"
    pre = Endpointer(preroll=speech(0.5), already_speaking=True, ignore_s=0.3)
    assert [pre.feed(f) for f in frames_of(silence(1.4))][-1] == "done"
    assert 1.6 <= len(pre.audio()) / RATE <= 1.8  # 0,5 s prévio + 0,3 s ignorado + 0,9 s de silêncio


def test_ring_buffer_and_resample():
    ring = RingBuffer(seconds=1.0)
    for f in frames_of(speech(3.0)):
        ring.append(f)
    assert abs(len(ring.last(0.5)) / RATE - 0.5) < 0.03
    assert len(resample_to_16k(np.zeros(48_000, dtype=np.float32), 48_000)) == 16_000
    assert abs(len(resample_to_16k(np.zeros(44_100, dtype=np.float32), 44_100)) - 16_000) <= 1


def test_safe_extract_blocks_zip_slip(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../fora.txt", "x")
    with pytest.raises(ValueError):
        safe_extract(bad, tmp_path / "out")


# --- Motor completo com componentes simulados ----------------------------------


class FakeMic:
    device_label = "Microfone de teste"

    def __init__(self, device=""):
        self.started = False

    def start(self, on_frame):
        self.started = True

    def stop(self):
        self.started = False


class FakeSpotter:
    def __init__(self, *_args, **_kwargs):
        self.next: list[str] = []

    def feed(self, frame):
        return self.next.pop(0) if self.next else None

    def reset(self):
        pass


class FakeTranscriber:
    def __init__(self, *_args, **_kwargs):
        self.replies: list[str] = []

    def load(self):
        pass

    def transcribe(self, audio):
        return self.replies.pop(0) if self.replies else ""


@pytest.fixture
def voice_env(settings, tmp_path):
    (settings.models_dir / "vosk-model-small-pt-0.3" / "am").mkdir(parents=True)
    (settings.models_dir / "whisper" / "small").mkdir(parents=True)
    (settings.models_dir / "whisper" / "small" / "model.bin").write_bytes(b"x")
    provider = ScriptedProvider()
    spotter, transcriber, speaker = FakeSpotter(), FakeTranscriber(), NullSpeaker()
    sexta = build_sexta(
        settings,
        provider=provider,
        voice_factories={
            "mic_factory": FakeMic,
            "spotter_factory": lambda *a, **k: spotter,
            "transcriber_factory": lambda *a, **k: transcriber,
            "speaker_factory": lambda **k: speaker,
            "tones": Tones(enabled=False),
            "auto_download": False,
        },
    )
    yield sexta, provider, spotter, transcriber, speaker
    sexta.close()


async def wait_for(predicate, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condição não atingida a tempo")
        await asyncio.sleep(0.02)


async def feed(engine, signal):
    for f in frames_of(signal):
        engine.process_frame(f)
    await asyncio.sleep(0)


async def start_engine(sexta):
    sexta.voice.start(asyncio.get_running_loop())
    await wait_for(lambda: sexta.voice.state in ("idle", "error"))
    assert sexta.voice.state == "idle", sexta.voice.error


async def test_wake_word_command_and_spoken_answer(voice_env):
    sexta, provider, spotter, transcriber, speaker = voice_env
    provider.add([text("São **três** horas.")])
    await start_engine(sexta)
    queue = sexta.bus.subscribe()

    spotter.next = ["wake"]
    transcriber.replies = ["Olá, Sexta-Feira, que horas são?"]
    await feed(sexta.voice, speech(0.1))
    assert sexta.voice.state == "listening"
    await feed(sexta.voice, np.concatenate([speech(0.8), silence(1.2)]))
    await wait_for(lambda: speaker.spoken)
    assert speaker.spoken[-1] == "São três horas."
    request = provider.requests[0]
    assert request.messages[-1]["content"][1]["text"] == "que horas são?"
    assert "canal: voz" in request.messages[-1]["content"][0]["text"]
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert any(e["type"] == "voice_command" for e in events)
    assert any(e["type"] == "voice_state" and e["state"] == "listening" for e in events)
    await wait_for(lambda: sexta.voice.state == "idle")


async def test_double_clap_activates_and_reuses_conversation(voice_env):
    sexta, provider, _spotter, transcriber, speaker = voice_env
    provider.add([text("Primeira resposta.")]).add([text("Segunda resposta.")])
    await start_engine(sexta)

    transcriber.replies = ["qual é a capital da França?"]
    await feed(sexta.voice, np.concatenate([silence(1), clap(), silence(0.35), clap()]))
    assert sexta.voice.state == "listening"
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.8), silence(1.2)]))
    await wait_for(lambda: len(speaker.spoken) == 1)
    first_conversation = sexta.voice.conversation_id

    await wait_for(lambda: sexta.voice.state == "idle")
    sexta.voice.activate()
    transcriber.replies = ["e da Itália?"]
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.8), silence(1.2)]))
    await wait_for(lambda: len(speaker.spoken) == 2)
    assert sexta.voice.conversation_id == first_conversation  # continuidade da conversa


async def test_only_wake_phrase_then_command(voice_env):
    sexta, provider, spotter, transcriber, speaker = voice_env
    provider.add([text("Abrindo.")])
    await start_engine(sexta)
    spotter.next = ["wake"]
    transcriber.replies = ["Olá, Sexta-Feira.", "abra a calculadora"]
    await feed(sexta.voice, np.concatenate([speech(0.3), silence(1.2)]))
    await wait_for(lambda: sexta.voice.state == "listening" and not transcriber.replies[1:])  # esperando o pedido
    assert transcriber.replies == ["abra a calculadora"]
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.8), silence(1.2)]))
    await wait_for(lambda: speaker.spoken)
    assert provider.requests[0].messages[-1]["content"][1]["text"] == "abra a calculadora"


async def test_voice_approval_for_non_critical_action(voice_env):
    sexta, provider, _spotter, transcriber, speaker = voice_env
    provider.add([tool_use("tu1", "fs_write", {"path": "voz.txt", "content": "oi"})], stop_reason="tool_use").add(
        [text("Arquivo criado.")]
    )
    await start_engine(sexta)
    transcriber.replies = ["crie o arquivo voz.txt", "sim"]
    sexta.voice.activate()
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.8), silence(1.2)]))
    await wait_for(lambda: any("Diga sim ou não" in s for s in speaker.spoken))
    await wait_for(lambda: sexta.voice.state == "listening")
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.5), silence(1.2)]))
    await wait_for(lambda: "Arquivo criado." in speaker.spoken)
    assert (sexta.settings.workspace_dir / "voz.txt").read_text() == "oi"


async def test_critical_action_is_never_approved_by_voice(voice_env):
    sexta, provider, _spotter, transcriber, speaker = voice_env
    provider.add([tool_use("tu1", "shell_run", {"command": "rm notas.txt"})], stop_reason="tool_use")
    await start_engine(sexta)
    transcriber.replies = ["apague notas.txt"]
    sexta.voice.activate()
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.8), silence(1.2)]))
    await wait_for(lambda: any("confirme na tela" in s for s in speaker.spoken))
    assert sexta.approvals.pending()  # continua aguardando o clique
    assert sexta.voice._awaiting is None  # noqa: SLF001
    for task_id in sexta.tasks.running_ids():
        sexta.tasks.cancel(task_id)


async def test_stop_command_cancels_running_tasks(voice_env):
    sexta, provider, _spotter, transcriber, speaker = voice_env
    provider.add([text("demorado...")])
    provider.gate = asyncio.Event()  # a resposta nunca termina
    await start_engine(sexta)
    transcriber.replies = ["escreva um livro", "parar"]
    sexta.voice.activate()
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.8), silence(1.2)]))
    await wait_for(lambda: sexta.tasks.running_ids())
    sexta.voice.activate()
    await feed(sexta.voice, np.concatenate([silence(0.4), speech(0.5), silence(1.2)]))
    await wait_for(lambda: not sexta.tasks.running_ids())
    assert "Certo, interrompi." in speaker.spoken


async def test_missing_models_reports_clear_error(settings):
    sexta = build_sexta(
        settings,
        provider=ScriptedProvider(),
        voice_factories={"mic_factory": FakeMic, "tones": Tones(enabled=False), "auto_download": False},
    )
    try:
        sexta.voice.start(asyncio.get_running_loop())
        await wait_for(lambda: sexta.voice.state == "error")
        assert "sexta voz instalar" in sexta.voice.error
    finally:
        sexta.close()


async def test_engine_off_when_disabled(voice_env):
    sexta, *_ = voice_env
    sexta.runtime.update({"voice_engine": "navegador"})
    sexta.voice.start(asyncio.get_running_loop())
    await asyncio.sleep(0.05)
    assert sexta.voice.state == "off"


def test_model_store_status(tmp_path):
    store = ModelStore(tmp_path)
    assert store.status("small") == {"vosk": False, "whisper": False, "whisper_size": "small", "path": str(tmp_path)}
