"""Infraestrutura de ferramentas (as "mãos" da Sexta-Feira).

Uma ferramenta declara:
* ``args_model``: modelo Pydantic que valida a entrada vinda da IA;
* ``capability`` e ``risk``: usados pela política de permissões;
* ``assess`` (opcional): avalia o risco *desta* chamada (ex.: um comando ``rm`` é
  crítico, um ``ls`` não) e pode bloquear via guardas;
* ``handler``: a execução em si (assíncrona).

Para criar uma ferramenta nova: escreva o ``args_model`` e o ``handler`` num módulo
de ``tools/`` e adicione-a à lista ``TOOLS`` desse módulo.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ..llm.base import ToolSpec
from ..security.permissions import Risk

if TYPE_CHECKING:
    from ..config import Settings
    from ..core.runtime_settings import RuntimeSettings
    from ..memory.conversations import ConversationService
    from ..memory.memories import MemoryService
    from ..security.audit import AuditLog
    from ..security.guards import PathSandbox


@dataclass
class ToolContext:
    settings: Settings
    runtime: RuntimeSettings
    sandbox: PathSandbox
    memory: MemoryService
    conversations: ConversationService
    audit: AuditLog
    publish: Callable[[dict[str, Any]], Awaitable[None]]
    task_id: str | None = None
    conversation_id: str | None = None


@dataclass
class Assessment:
    risk: Risk
    summary: str
    blocked_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False
    data: Any = None


Handler = Callable[[Any, ToolContext], Awaitable["ToolOutput | str | dict[str, Any] | list[Any]"]]
Assessor = Callable[[Any, ToolContext], Assessment]


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    capability: str
    risk: Risk
    handler: Handler
    assess: Assessor | None = None
    timeout_s: float | None = None

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, clean_schema(self.args_model.model_json_schema()))

    def assessment(self, args: BaseModel, ctx: ToolContext) -> Assessment:
        if self.assess is not None:
            return self.assess(args, ctx)
        return Assessment(self.risk, summary=self.name)


def clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove ``title`` gerado pelo Pydantic (ruído no prompt) mantendo o resto."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return schema


def normalize_output(result: ToolOutput | str | dict[str, Any] | list[Any] | None) -> ToolOutput:
    if isinstance(result, ToolOutput):
        return result
    if result is None:
        return ToolOutput("ok")
    if isinstance(result, str):
        return ToolOutput(result)
    return ToolOutput(json.dumps(result, ensure_ascii=False, indent=1, default=str), data=result)


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Ferramenta duplicada: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        # Ordem estável: a lista de ferramentas faz parte do prefixo em cache.
        return [t.spec() for t in sorted(self._tools.values(), key=lambda t: t.name)]
