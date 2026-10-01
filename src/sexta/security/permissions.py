"""Modelo de permissões: níveis de autonomia × risco da ação × capacidade.

Princípio central: **a segurança é garantida pelo código, não pelo prompt.** A IA
pode pedir qualquer ferramenta; quem decide se ela roda é esta política.

Decisão para cada chamada de ferramenta:
1. Guardas rígidas (``guards.py``) podem bloquear de imediato (ex.: ``rm -rf /``).
2. Ações **críticas** nunca rodam sem confirmação (salvo se negadas).
3. Ajustes por capacidade feitos pelo usuário (permitir / perguntar / negar).
4. Matriz padrão do nível de autonomia escolhido.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Risk(StrEnum):
    SAFE = "safe"  # interno e reversível (consultar memória, salvar memória)
    READ = "read"  # lê dados do usuário/sistema
    WRITE = "write"  # altera arquivos ou dados
    EXEC = "exec"  # executa programas/comandos
    CRITICAL = "critical"  # destrutivo ou de alto impacto

    @property
    def label(self) -> str:
        return {
            "safe": "Seguro",
            "read": "Leitura",
            "write": "Escrita",
            "exec": "Execução",
            "critical": "Crítico",
        }[self.value]


class Action(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


CAPABILITIES: dict[str, str] = {
    "memory.read": "Consultar a memória",
    "memory.write": "Salvar e editar memórias",
    "history.read": "Consultar conversas e atividades anteriores",
    "fs.read": "Ler e listar arquivos",
    "fs.write": "Criar, editar e mover arquivos",
    "fs.delete": "Excluir arquivos (vão para a lixeira)",
    "shell.exec": "Executar comandos no terminal",
    "system.read": "Ler informações do sistema e processos",
    "process.control": "Encerrar processos",
    "apps.launch": "Abrir programas, arquivos e links",
    "web.search": "Pesquisar na internet",
}

AUTONOMY_LEVELS: dict[int, dict[str, str]] = {
    0: {"name": "Restrito", "description": "Só conversa e memória. Leituras pedem confirmação; nada é alterado."},
    1: {"name": "Assistido", "description": "Lê livremente; qualquer alteração ou execução pede confirmação."},
    2: {
        "name": "Supervisionado",
        "description": "Lê e edita arquivos sozinha; comandos e programas pedem confirmação.",
    },
    3: {"name": "Autônomo", "description": "Executa sozinha; apenas ações críticas pedem confirmação."},
}

DEFAULT_AUTONOMY = 1

_A, _Q, _D = Action.ALLOW, Action.ASK, Action.DENY
MATRIX: dict[int, dict[Risk, Action]] = {
    0: {Risk.SAFE: _A, Risk.READ: _Q, Risk.WRITE: _D, Risk.EXEC: _D, Risk.CRITICAL: _D},
    1: {Risk.SAFE: _A, Risk.READ: _A, Risk.WRITE: _Q, Risk.EXEC: _Q, Risk.CRITICAL: _Q},
    2: {Risk.SAFE: _A, Risk.READ: _A, Risk.WRITE: _A, Risk.EXEC: _Q, Risk.CRITICAL: _Q},
    3: {Risk.SAFE: _A, Risk.READ: _A, Risk.WRITE: _A, Risk.EXEC: _A, Risk.CRITICAL: _Q},
}


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    reason: str


def decide(
    capability: str,
    risk: Risk,
    *,
    autonomy: int,
    overrides: dict[str, str] | None = None,
) -> PolicyDecision:
    level = autonomy if autonomy in MATRIX else DEFAULT_AUTONOMY
    override = (overrides or {}).get(capability)
    level_name = AUTONOMY_LEVELS[level]["name"]

    if override == Action.DENY:
        return PolicyDecision(Action.DENY, f"Capacidade '{capability}' bloqueada nas configurações.")

    if risk == Risk.CRITICAL:
        if level == 0 and override != Action.ALLOW:
            return PolicyDecision(Action.DENY, f"Ações críticas não são permitidas no nível {level_name}.")
        return PolicyDecision(Action.ASK, "Ação crítica: sempre exige sua confirmação.")

    if override == Action.ALLOW:
        return PolicyDecision(Action.ALLOW, f"Capacidade '{capability}' liberada nas configurações.")
    if override == Action.ASK:
        return PolicyDecision(Action.ASK, f"Capacidade '{capability}' configurada para pedir confirmação.")

    action = MATRIX[level][risk]
    reasons = {
        Action.ALLOW: f"Permitido pelo nível {level_name} (risco: {risk.label}).",
        Action.ASK: f"Nível {level_name} exige confirmação para risco '{risk.label}'.",
        Action.DENY: f"Nível {level_name} não permite ações de risco '{risk.label}'.",
    }
    return PolicyDecision(action, reasons[action])
