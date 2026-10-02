"""Executor de ferramentas: valida → avalia risco → decide → (confirma) → executa → audita.

Toda chamada de ferramenta feita pela IA passa por aqui. O resultado volta para a
IA como ``tool_result``; erros e negações também voltam (com ``is_error``), para
que ela possa explicar ou tentar outro caminho.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Any

from pydantic import ValidationError

from ..security.approvals import ApprovalBroker, ApprovalRequest
from ..security.audit import AuditLog
from ..security.guards import GuardError, SecretRedactor
from ..security.permissions import Action, decide
from .base import ToolContext, ToolOutput, ToolRegistry, normalize_output


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        approvals: ApprovalBroker,
        audit: AuditLog,
        redactor: SecretRedactor,
        *,
        default_timeout_s: float = 60.0,
        max_output_chars: int = 20_000,
    ):
        self.registry = registry
        self.approvals = approvals
        self.audit = audit
        self.redactor = redactor
        self.default_timeout_s = default_timeout_s
        self.max_output_chars = max_output_chars

    async def run(self, block: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        tool_use_id = str(block.get("id"))
        name = str(block.get("name"))
        raw_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        base_event = {
            "task_id": ctx.task_id,
            "conversation_id": ctx.conversation_id,
            "tool_use_id": tool_use_id,
            "tool": name,
        }

        async def finish(output: ToolOutput, status: str) -> dict[str, Any]:
            content = self.redactor(output.content)
            if len(content) > self.max_output_chars:
                omitted = len(content) - self.max_output_chars
                content = content[: self.max_output_chars] + f"\n\n[... {omitted} caracteres omitidos]"
            await ctx.publish(
                {
                    "type": "tool_status",
                    **base_event,
                    "status": status,
                    "result": content[:4000],
                    "is_error": output.is_error,
                }
            )
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
            if output.images:
                result["content"] = [
                    {"type": "text", "text": content},
                    *(
                        {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
                        for media, data in output.images[:3]
                    ),
                ]
            if output.is_error:
                result["is_error"] = True
            return result

        ctx = dataclasses.replace(ctx, tool_use_id=tool_use_id)
        tool = self.registry.get(name)
        if tool is None:
            return await finish(ToolOutput(f"Ferramenta desconhecida: {name}", is_error=True), "error")

        # 1) Validação da entrada
        try:
            args = tool.args_model.model_validate(raw_input)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'entrada'}: {e['msg']}" for e in exc.errors()[:5])
            return await finish(ToolOutput(f"Entrada inválida para {name}: {problems}", is_error=True), "error")

        # 2) Avaliação de risco + guardas rígidas
        try:
            assessment = tool.assessment(args, ctx)
        except GuardError as exc:
            self.audit.record(
                "tool_blocked",
                task_id=ctx.task_id,
                conversation_id=ctx.conversation_id,
                tool=name,
                capability=tool.capability,
                risk="critical",
                decision="deny",
                detail={"input": raw_input, "reason": str(exc)},
            )
            return await finish(ToolOutput(f"Bloqueado pela segurança: {exc}", is_error=True), "blocked")

        await ctx.publish(
            {
                "type": "tool_status",
                **base_event,
                "status": "evaluating",
                "input": raw_input,
                "risk": assessment.risk.value,
                "summary": assessment.summary,
            }
        )

        if assessment.blocked_reason:
            self.audit.record(
                "tool_blocked",
                task_id=ctx.task_id,
                conversation_id=ctx.conversation_id,
                tool=name,
                capability=tool.capability,
                risk=assessment.risk.value,
                decision="deny",
                detail={"input": raw_input, "reason": assessment.blocked_reason},
            )
            return await finish(
                ToolOutput(
                    f"Bloqueado pela segurança: {assessment.blocked_reason}. Esta ação nunca é permitida.",
                    is_error=True,
                ),
                "blocked",
            )

        # 3) Política de permissões
        decision = decide(
            tool.capability,
            assessment.risk,
            autonomy=ctx.runtime.autonomy_level,
            overrides=ctx.runtime.permission_overrides,
        )
        self.audit.record(
            "tool_decision",
            task_id=ctx.task_id,
            conversation_id=ctx.conversation_id,
            tool=name,
            capability=tool.capability,
            risk=assessment.risk.value,
            decision=decision.action.value,
            detail={"input": raw_input, "reason": decision.reason, "summary": assessment.summary},
        )

        if decision.action == Action.DENY:
            return await finish(
                ToolOutput(f"Ação negada pela política de permissões: {decision.reason}", is_error=True), "denied"
            )

        if decision.action == Action.ASK:
            await ctx.publish({"type": "tool_status", **base_event, "status": "awaiting_approval"})
            approved = await self.approvals.request(
                ApprovalRequest(
                    id="",
                    task_id=ctx.task_id,
                    conversation_id=ctx.conversation_id,
                    tool=name,
                    capability=tool.capability,
                    risk=assessment.risk.value,
                    summary=assessment.summary,
                    reason=decision.reason,
                    details={"input": raw_input, **assessment.details},
                )
            )
            self.audit.record(
                "tool_approval",
                task_id=ctx.task_id,
                conversation_id=ctx.conversation_id,
                tool=name,
                capability=tool.capability,
                risk=assessment.risk.value,
                decision="approved" if approved else "rejected",
                detail={"summary": assessment.summary},
            )
            if not approved:
                return await finish(
                    ToolOutput(
                        "O usuário não autorizou esta ação (ou o tempo de confirmação expirou). Não tente contornar; pergunte como prefere seguir.",
                        is_error=True,
                    ),
                    "rejected",
                )

        # 4) Execução
        await ctx.publish({"type": "tool_status", **base_event, "status": "running"})
        started = time.perf_counter()
        try:
            raw = await asyncio.wait_for(tool.handler(args, ctx), timeout=tool.timeout_s or self.default_timeout_s)
            output = normalize_output(raw)
        except GuardError as exc:
            output = ToolOutput(f"Bloqueado pela segurança: {exc}", is_error=True)
        except TimeoutError:
            output = ToolOutput("A ferramenta excedeu o tempo limite e foi interrompida.", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — qualquer falha vira resultado de erro para a IA
            output = ToolOutput(f"Falha ao executar {name}: {type(exc).__name__}: {exc}", is_error=True)
        duration_ms = int((time.perf_counter() - started) * 1000)
        self.audit.record(
            "tool_executed",
            task_id=ctx.task_id,
            conversation_id=ctx.conversation_id,
            tool=name,
            capability=tool.capability,
            risk=assessment.risk.value,
            decision=decision.action.value,
            success=not output.is_error,
            duration_ms=duration_ms,
            detail={"summary": assessment.summary, "output": self.redactor(output.content)[:1000]},
        )
        return await finish(output, "error" if output.is_error else "done")
