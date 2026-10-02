"""Montagem do sistema (injeção de dependências manual e explícita).

Este é o único lugar que sabe *como* as peças se conectam. Testes e futuras
interfaces (CLI, voz, app de celular) reutilizam ``build_sexta``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .core.events import EventBus
from .core.orchestrator import Orchestrator
from .core.router import Router
from .core.runtime_settings import RuntimeSettingsStore
from .core.tasks import TaskManager
from .core.usage import UsageTracker
from .llm import build_provider
from .llm.base import LLMProvider
from .llm.catalog import Tier
from .memory.conversations import ConversationService
from .memory.db import Database
from .memory.memories import MemoryService
from .security.approvals import ApprovalBroker
from .security.audit import AuditLog
from .security.guards import SecretRedactor
from .tools import build_default_registry
from .tools.base import ToolRegistry
from .tools.executor import ToolExecutor
from .winsys import AutostartManager, RunKey


@dataclass
class Sexta:
    settings: Settings
    db: Database
    runtime: RuntimeSettingsStore
    conversations: ConversationService
    memory: MemoryService
    usage: UsageTracker
    audit: AuditLog
    bus: EventBus
    approvals: ApprovalBroker
    tasks: TaskManager
    registry: ToolRegistry
    executor: ToolExecutor
    router: Router
    provider: LLMProvider
    orchestrator: Orchestrator
    autostart: AutostartManager

    def close(self) -> None:
        self.db.close()


def build_sexta(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
    registry: ToolRegistry | None = None,
    run_key: RunKey | None = None,
) -> Sexta:
    settings = settings or Settings()
    settings.ensure_dirs()

    db = Database(settings.db_path)
    bus = EventBus()
    runtime = RuntimeSettingsStore(db, settings)
    conversations = ConversationService(db)
    memory = MemoryService(db)
    usage = UsageTracker(db)
    audit = AuditLog(db)
    approvals = ApprovalBroker(bus, timeout_s=settings.approval_timeout_s)
    tasks = TaskManager(db)
    tasks.mark_interrupted()

    registry = registry or build_default_registry()
    redactor = SecretRedactor([s for s in (settings.api_key, settings.token) if s])
    executor = ToolExecutor(
        registry,
        approvals,
        audit,
        redactor,
        default_timeout_s=settings.tool_timeout_s,
        max_output_chars=settings.max_tool_output_chars,
    )
    router = Router(
        {
            Tier.FAST: settings.model_fast,
            Tier.BALANCED: settings.model_balanced,
            Tier.DEEP: settings.model_deep,
        }
    )
    provider = provider or build_provider(settings)
    orchestrator = Orchestrator(
        settings=settings,
        runtime=runtime,
        conversations=conversations,
        memory=memory,
        usage=usage,
        audit=audit,
        registry=registry,
        executor=executor,
        router=router,
        provider=provider,
        bus=bus,
        tasks=tasks,
    )
    return Sexta(
        settings=settings,
        db=db,
        runtime=runtime,
        conversations=conversations,
        memory=memory,
        usage=usage,
        audit=audit,
        bus=bus,
        approvals=approvals,
        tasks=tasks,
        registry=registry,
        executor=executor,
        router=router,
        provider=provider,
        orchestrator=orchestrator,
        autostart=AutostartManager(Path.cwd(), run_key),
    )
