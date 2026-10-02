"""Montagem do sistema (injeção de dependências manual e explícita).

Este é o único lugar que sabe *como* as peças se conectam. Testes e futuras
interfaces (CLI, voz, app de celular) reutilizam ``build_sexta``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .agents.delegation import Delegator
from .config import Settings
from .core.events import EventBus
from .core.orchestrator import Orchestrator
from .core.router import Router
from .core.runtime_settings import RuntimeSettingsStore
from .core.tasks import TaskManager
from .core.usage import UsageTracker
from .intel.alerts import AlertService
from .intel.briefing import BriefingService
from .intel.http import HttpClient
from .intel.scheduler import Scheduler
from .intel.service import IntelService
from .llm import build_provider
from .llm.base import LLMProvider
from .llm.catalog import Tier
from .memory.conversations import ConversationService
from .memory.db import Database
from .memory.memories import MemoryService
from .memory.semantic import Embedder, FastEmbedEmbedder, SemanticIndex
from .security.approvals import ApprovalBroker
from .security.audit import AuditLog
from .security.guards import SecretRedactor
from .tools import build_default_registry
from .tools.base import ToolRegistry
from .tools.executor import ToolExecutor
from .voice.engine import VoiceEngine
from .voice.models import ModelStore
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
    models: ModelStore
    voice: VoiceEngine
    intel: IntelService
    alerts: AlertService
    briefings: BriefingService
    scheduler: Scheduler
    semantic: SemanticIndex
    delegator: Delegator

    def close(self) -> None:
        self.voice.shutdown()
        self.db.close()


def build_sexta(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
    registry: ToolRegistry | None = None,
    run_key: RunKey | None = None,
    voice_factories: dict | None = None,
    http: HttpClient | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> Sexta:
    settings = settings or Settings()
    settings.ensure_dirs()

    db = Database(settings.db_path)
    bus = EventBus()
    runtime = RuntimeSettingsStore(db, settings)
    conversations = ConversationService(db)
    models = ModelStore(settings.models_dir)
    semantic = SemanticIndex(
        db,
        embedder_factory or (lambda: FastEmbedEmbedder(models.embeddings_dir)),
        enabled=lambda: runtime.get().semantic_memory,
    )
    memory = MemoryService(db, semantic)
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
    intel = IntelService(db, runtime, http)
    alerts = AlertService(db, bus)
    briefings = BriefingService(db, intel, alerts, orchestrator, bus)
    scheduler = Scheduler(db, runtime, intel, alerts, briefings)
    delegator = Delegator(orchestrator)
    orchestrator.services.update(intel=intel, alerts=alerts, delegator=delegator)

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
        models=models,
        voice=VoiceEngine(
            runtime=runtime,
            orchestrator=orchestrator,
            bus=bus,
            approvals=approvals,
            tasks=tasks,
            models=models,
            **(voice_factories or {}),
        ),
        intel=intel,
        alerts=alerts,
        briefings=briefings,
        scheduler=scheduler,
        semantic=semantic,
        delegator=delegator,
    )
