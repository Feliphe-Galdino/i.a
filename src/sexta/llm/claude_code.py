"""Provedor "assinatura": usa o Claude Code (CLI ``claude``) logado na sua conta Claude Pro/Max.

Por que existe: a API da Anthropic é cobrada à parte (créditos), mas o plano Pro já inclui
o Claude Code. Este provedor chama ``claude -p`` (modo não interativo, documentado para
automação) como se fosse a API — sem custo extra, consumindo os limites do seu plano.

Como funciona, sem abrir mão das regras da Sexta-Feira:

* O Claude Code roda **sem nenhuma ferramenta própria** (``--tools ""``) e sem
  personalizações (``--safe-mode``), numa pasta vazia: ele só pensa e escreve.
* As ferramentas da Sexta-Feira são descritas no prompt de sistema; quando a IA quer usar
  uma, escreve ``<tool_call>{"name": ..., "input": ...}</tool_call>``. Este provedor
  converte isso em blocos ``tool_use`` normais — então o orquestrador, o executor, as
  permissões, as aprovações e a auditoria funcionam exatamente como com a API.
* O histórico (formato canônico de content blocks) é enviado como uma transcrição a cada
  chamada; imagens (capturas de tela) seguem como imagens.
* A chave ``ANTHROPIC_API_KEY`` é removida do ambiente do subprocesso: o Claude Code
  usa SEMPRE o login da assinatura e nunca gera cobrança na API.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Completion, LLMError, LLMEvent, LLMRequest, TextDelta, ToolSpec, ToolUseStarted, Usage

log = logging.getLogger(__name__)

NAME = "claude-code"
TIMEOUT_S = 15 * 60
OPEN_TAG, CLOSE_TAG = "<tool_call>", "</tool_call>"
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
# Variáveis que fariam o Claude Code cobrar na API em vez de usar a assinatura (ou vazar segredos).
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "SEXTA_ANTHROPIC_API_KEY", "SEXTA_ACCESS_TOKEN")
OPTIONAL_FLAGS = ("--safe-mode", "--effort", "--fallback-model", "--include-partial-messages")

PROTOCOL = """

## Ferramentas da Sexta-Feira (protocolo obrigatório)
Nesta sessão você NÃO tem ferramentas nativas. As ferramentas abaixo são executadas pelo sistema \
da Sexta-Feira (com as permissões e confirmações do usuário). Para usar uma, escreva um bloco \
exatamente neste formato, com JSON válido:
<tool_call>{"name": "NOME_DA_FERRAMENTA", "input": {…argumentos…}}</tool_call>
- Pode pedir várias ferramentas de uma vez (um bloco para cada).
- Depois do(s) bloco(s), PARE de escrever: o sistema executa e devolve os resultados em \
<resultado_ferramenta>; aí você continua. Não escreva "aguarde" nem antecipe resultados.
- Nunca invente resultados de ferramentas e nunca escreva blocos <resultado_ferramenta>.
- Dizer que salvou, anotou, abriu ou consultou algo SEM o bloco é falso: a ação não acontece. Na dúvida, \
use a ferramenta.
- A conversa chega como transcrição em <conversa>; responda apenas com a próxima fala da assistente.
{web}
Ferramentas disponíveis:
{tools}"""

# Vai no FIM de cada pedido (o que é lido por último pesa mais): sem bloco, nada acontece.
REMINDER = (
    "Escreva agora somente a próxima resposta da assistente. Lembrete do sistema: ações (salvar memória, "
    "consultar dados, abrir sites, mexer em arquivos…) SÓ acontecem com blocos <tool_call>. Se a resposta "
    "precisa de uma ação, inclua o bloco agora; nunca diga que fez, salvou ou consultou algo sem ele."
)

# Ferramentas nativas ficam SEMPRE desligadas: com qualquer uma ligada, o modelo tenta chamar as
# ferramentas da Sexta-Feira como nativas (e falha). A busca na web usa as ferramentas da própria Sexta.
WEB_HINT_ON = (
    "- Para pesquisar na internet: web_fetch com https://html.duckduckgo.com/html/?q=TERMOS (resultados) e "
    "depois web_fetch nas páginas; notícias recentes: news_search; sites interativos: browser_open."
)
WEB_HINT_OFF = ""


# --- Localizar o executável -------------------------------------------------------------


def find_claude(override: str | None = None) -> str | None:
    """Caminho do ``claude``: variável SEXTA_CLAUDE_PATH, PATH ou locais comuns do Windows."""
    candidates = [override, os.environ.get("SEXTA_CLAUDE_PATH")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    extra = [home / ".local" / "bin" / "claude.exe", home / ".local" / "bin" / "claude"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        extra.append(Path(appdata) / "npm" / "claude.cmd")
    return next((str(p) for p in extra if p.exists()), None)


# --- Transcrição ---------------------------------------------------------------------------


def _neutralize(text: str) -> str:
    """Dados externos não podem fechar/abrir as marcações do protocolo."""
    return (
        text.replace("<tool_call", "<tool-call")
        .replace("</tool_call", "</tool-call")
        .replace("</resultado_ferramenta", "</resultado-ferramenta")
        .replace("</conversa", "</conversa_")
    )


def render_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converte o histórico (content blocks) em blocos de texto/imagem para uma única mensagem."""
    blocks: list[dict[str, Any]] = []
    buffer: list[str] = ["<conversa>"]
    names: dict[str, str] = {}

    def flush() -> None:
        if buffer:
            blocks.append({"type": "text", "text": "\n".join(buffer)})
            buffer.clear()

    for message in messages:
        role, content = message.get("role"), message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if role == "assistant":
            parts = []
            for block in content or []:
                kind = block.get("type")
                if kind == "text" and block.get("text"):
                    parts.append(block["text"])
                elif kind == "tool_use":
                    names[block.get("id", "")] = block.get("name", "")
                    payload = {"id": block.get("id"), "name": block.get("name"), "input": block.get("input", {})}
                    parts.append(f"{OPEN_TAG}{json.dumps(payload, ensure_ascii=False)}{CLOSE_TAG}")
            if parts:
                buffer.append("<assistente>\n" + "\n".join(parts) + "\n</assistente>")
            continue
        user_parts: list[str] = []
        for block in content or []:
            kind = block.get("type")
            if kind == "text":
                user_parts.append(block.get("text", ""))
            elif kind == "tool_result":
                if user_parts:
                    buffer.append("<usuario>\n" + "\n".join(user_parts) + "\n</usuario>")
                    user_parts = []
                tool_id = block.get("tool_use_id", "")
                status = ' erro="sim"' if block.get("is_error") else ""
                head = f'<resultado_ferramenta id="{tool_id}" nome="{names.get(tool_id, "")}"{status}>'
                inner = block.get("content")
                if isinstance(inner, list):
                    buffer.append(head)
                    for part in inner:
                        if part.get("type") == "text":
                            buffer.append(_neutralize(part.get("text", "")))
                        elif part.get("type") == "image":
                            flush()
                            blocks.append({"type": "image", "source": part["source"]})
                    buffer.append("</resultado_ferramenta>")
                else:
                    buffer.append(f"{head}\n{_neutralize(str(inner or ''))}\n</resultado_ferramenta>")
            elif kind == "image" and block.get("source"):
                flush()
                blocks.append({"type": "image", "source": block["source"]})
        if user_parts:
            buffer.append("<usuario>\n" + "\n".join(user_parts) + "\n</usuario>")
    buffer.append("</conversa>")
    buffer.append(REMINDER)
    flush()
    return blocks


def build_system(request: LLMRequest, web_search: bool) -> str:
    tools = "\n".join(_tool_line(spec) for spec in request.tools) or "(nenhuma nesta conversa)"
    return request.system + PROTOCOL.replace("{web}", WEB_HINT_ON if web_search else WEB_HINT_OFF).replace(
        "{tools}", tools
    )


def _tool_line(spec: ToolSpec) -> str:
    schema = json.dumps(spec.input_schema, ensure_ascii=False, separators=(",", ":"))
    return f"- {spec.name}: {spec.description}\n  entrada (JSON Schema): {schema}"


# --- Leitura da resposta -----------------------------------------------------------------


class TagFilter:
    """Esconde os blocos <tool_call>…</tool_call> do texto mostrado em tempo real."""

    def __init__(self) -> None:
        self.pending = ""
        self.inside = False

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        out = []
        while self.pending:
            if self.inside:
                end = self.pending.find(CLOSE_TAG)
                if end < 0:
                    self.pending = self.pending[-(len(CLOSE_TAG) - 1) :]
                    break
                self.pending = self.pending[end + len(CLOSE_TAG) :]
                self.inside = False
                continue
            start = self.pending.find(OPEN_TAG)
            if start >= 0:
                out.append(self.pending[:start])
                self.pending = self.pending[start + len(OPEN_TAG) :]
                self.inside = True
                continue
            keep = next((n for n in range(len(OPEN_TAG) - 1, 0, -1) if self.pending.endswith(OPEN_TAG[:n])), 0)
            out.append(self.pending[: len(self.pending) - keep])
            self.pending = self.pending[len(self.pending) - keep :]
            break
        return "".join(out)


def parse_output(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Separa o texto visível das chamadas de ferramenta."""
    calls: list[dict[str, Any]] = []
    for raw in TOOL_CALL_RE.findall(text):
        tool_id = "toolu_cc_" + uuid.uuid4().hex[:20]
        try:
            data = json.loads(raw)
            name, args = str(data.get("name", "")), data.get("input", {})
            if not isinstance(args, dict):
                args = {"valor": args}
        except (json.JSONDecodeError, AttributeError):
            match = re.search(r'"name"\s*:\s*"([^"]+)"', raw)
            name = match.group(1) if match else "chamada_invalida"
            args = {"__json_invalido__": raw[:500]}  # o executor devolve erro e a IA corrige
        calls.append({"type": "tool_use", "id": tool_id, "name": name, "input": args})
    visible = TOOL_CALL_RE.sub("", text)
    if OPEN_TAG in visible:  # bloco aberto e não fechado (resposta cortada)
        visible = visible.split(OPEN_TAG, 1)[0]
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    return visible, calls


def friendly_error(message: str, rate_limit: dict[str, Any] | None = None) -> LLMError:
    lowered = message.lower()
    if (
        "limit" in lowered
        and ("usage" in lowered or "reached" in lowered or "rate" in lowered)
        or (rate_limit and rate_limit.get("status") == "rejected")
    ):
        when = ""
        if rate_limit and rate_limit.get("resetsAt"):
            when = (
                " Ele renova às " + datetime.fromtimestamp(int(rate_limit["resetsAt"])).strftime("%H:%M (%d/%m)") + "."
            )
        return LLMError(
            "Você atingiu o limite de uso do seu plano Claude por enquanto." + when + " Até lá a IA fica pausada "
            "(voz, mundo, memória e alertas continuam funcionando).",
            retryable=False,
        )
    if any(k in lowered for k in ("/login", "not logged", "log in", "authenticat", "oauth", "invalid api key", "401")):
        return LLMError(
            "O Claude Code não está conectado à sua conta. Abra o PowerShell, rode  claude  e entre com sua "
            "conta Claude Pro (é só uma vez). Depois tente de novo."
        )
    return LLMError(f"O Claude Code não conseguiu responder: {message.strip()[:400]}", retryable=True)


# --- Execução ------------------------------------------------------------------------------

Runner = Callable[[list[str], bytes, Path, dict[str, str]], AsyncIterator[str]]


async def run_process(args: list[str], stdin: bytes, cwd: Path, env: dict[str, str]) -> AsyncIterator[str]:
    """Roda o CLI e devolve as linhas da saída (JSON por linha). Erros → LLMError."""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: sem janela de console piscando
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            limit=32 * 1024 * 1024,
            **kwargs,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise LLMError(f"Não consegui executar o Claude Code ({exc}).") from exc
    try:
        assert proc.stdin and proc.stdout and proc.stderr
        proc.stdin.write(stdin)
        await proc.stdin.drain()
        proc.stdin.close()
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=TIMEOUT_S)
            if not line:
                break
            yield line.decode("utf-8", errors="replace")
        await proc.wait()
        if proc.returncode:
            err = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
            yield json.dumps({"type": "_exit", "code": proc.returncode, "stderr": err})
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()


class ClaudeCodeProvider:
    """Implementa ``LLMProvider`` sobre o ``claude -p`` (assinatura Claude Pro/Max)."""

    name = NAME

    def __init__(self, workdir: Path, *, executable: str | None = None, runner: Runner | None = None):
        self.workdir = Path(workdir)
        self.executable = executable or find_claude()
        self.runner = runner or run_process
        self.unsupported: set[str] = set()
        self.rate_limit: dict[str, Any] | None = None  # último retrato do uso do plano

    def plan_usage(self) -> dict[str, Any] | None:
        """Uso do plano informado pelo Claude Code (janela de 5 h e semanal)."""
        info = self.rate_limit
        if not info:
            return None
        windows = info.get("unifiedWindows") or {}
        return {
            "status": info.get("status"),
            "five_hour": windows.get("five_hour"),
            "seven_day": windows.get("seven_day"),
            "resets_at": info.get("resetsAt"),
        }

    def _args(self, request: LLMRequest, system_file: Path) -> list[str]:
        if not self.executable:
            raise LLMError(
                "Claude Code não encontrado. Instale (PowerShell):  irm https://claude.ai/install.ps1 | iex  "
                "e depois rode  claude  uma vez para entrar com sua conta Claude Pro."
            )
        args = [
            self.executable,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "--safe-mode",
            "--system-prompt-file",
            str(system_file),
            "--model",
            request.model,
        ]
        args += ["--tools", ""]  # nenhuma ferramenta nativa (ver WEB_HINT_ON)
        if request.effort:
            args += ["--effort", request.effort]
        fallback = "claude-haiku-4-5" if "sonnet" in request.model else "claude-sonnet-5-5"
        if "haiku" not in request.model:
            args += ["--fallback-model", fallback]
        return self._strip_unsupported(args)

    def _strip_unsupported(self, args: list[str]) -> list[str]:
        out, skip = [], False
        for i, arg in enumerate(args):
            if skip:
                skip = False
                continue
            if arg in self.unsupported:
                skip = arg in ("--effort", "--fallback-model") and i + 1 < len(args)
                continue
            out.append(arg)
        return out

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        return env

    def _system_file(self, text: str) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        path = self.workdir / f"sistema-{hashlib.sha256(text.encode()).hexdigest()[:16]}.txt"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            for old in sorted(self.workdir.glob("sistema-*.txt"), key=lambda p: p.stat().st_mtime)[:-20]:
                with contextlib.suppress(OSError):
                    old.unlink()
        return path

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        web_search = bool(request.web_search) and any(t.name == "web_fetch" for t in request.tools)
        system_file = self._system_file(build_system(request, web_search))
        message = {"type": "user", "message": {"role": "user", "content": render_transcript(request.messages)}}
        stdin = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

        for _attempt in range(len(OPTIONAL_FLAGS) + 1):
            args = self._args(request, system_file)
            texts: list[str] = []
            tag_filter = TagFilter()
            result: dict[str, Any] | None = None
            model = request.model
            exit_info: dict[str, Any] | None = None
            async for line in self.runner(args, stdin, self.workdir, self._env()):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta":
                        visible = tag_filter.feed(delta.get("text", ""))
                        if visible:
                            yield TextDelta(visible)
                elif kind == "assistant":
                    msg = event.get("message") or {}
                    model = msg.get("model") or model
                    for block in msg.get("content") or []:
                        if block.get("type") == "text" and block.get("text"):
                            texts.append(block["text"])
                elif kind == "rate_limit_event":
                    self.rate_limit = event.get("rate_limit_info") or self.rate_limit
                elif kind == "result":
                    result = event
                elif kind == "_exit":
                    exit_info = event
            if result is None and exit_info:
                stderr = exit_info.get("stderr", "")
                missing = re.search(r"unknown option '(--[\w-]+)'", stderr)
                if missing and missing.group(1) in OPTIONAL_FLAGS and missing.group(1) not in self.unsupported:
                    log.info("Claude Code antigo: removendo a opção %s", missing.group(1))
                    self.unsupported.add(missing.group(1))
                    continue  # tenta de novo sem a opção que esta versão não conhece
                raise friendly_error(stderr or f"código de saída {exit_info.get('code')}", self.rate_limit)
            break
        if result is None:
            raise LLMError("O Claude Code encerrou sem resposta.", retryable=True)
        if result.get("is_error") or result.get("subtype") not in (None, "success"):
            raise friendly_error(
                str(result.get("result") or result.get("errors") or result.get("subtype")), self.rate_limit
            )

        full_text = "\n\n".join(texts) if texts else str(result.get("result") or "")
        visible, calls = parse_output(full_text)
        for call in calls:
            yield ToolUseStarted(call["id"], call["name"])
        content: list[dict[str, Any]] = ([{"type": "text", "text": visible}] if visible else []) + calls
        if not content:
            content = [{"type": "text", "text": "…"}]
        usage_raw = result.get("usage") or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("input_tokens") or 0),
            output_tokens=int(usage_raw.get("output_tokens") or 0),
            cache_read_tokens=int(usage_raw.get("cache_read_input_tokens") or 0),
            cache_write_tokens=int(usage_raw.get("cache_creation_input_tokens") or 0),
        )
        yield Completion(
            content=content,
            stop_reason="tool_use" if calls else "end_turn",
            model=_base_model(model),
            usage=usage,
        )


def _base_model(model: str) -> str:
    """'claude-haiku-4-5-20251001' → 'claude-haiku-4-5' (para o catálogo e a interface)."""
    return re.sub(r"-\d{8}$", "", model or "")
