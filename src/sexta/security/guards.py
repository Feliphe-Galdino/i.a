"""Guardas rígidas: verificações que nenhuma configuração ou instrução da IA contorna.

* ``PathSandbox``: arquivos só dentro das pastas liberadas; caminhos sensíveis
  (chaves SSH, credenciais, o próprio banco da Sexta-Feira) são sempre bloqueados.
* ``classify_command``: classifica comandos de terminal; padrões catastróficos são
  bloqueados e padrões destrutivos viram "críticos" (sempre pedem confirmação).
* ``redact_secrets`` / ``safe_env``: impedem que segredos vazem para a IA ou para
  subprocessos.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .permissions import Risk


class GuardError(Exception):
    """Ação bloqueada por uma guarda de segurança."""


# --------------------------------------------------------------------------
# Sandbox de arquivos
# --------------------------------------------------------------------------

SENSITIVE_NAMES = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    ".netrc",
    ".git-credentials",
    ".pypirc",
    ".npmrc",
    ".env",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "known_hosts",
    "login data",  # senhas salvas do Chrome/Edge
    "cookies",
    "keychain",
    "keychains",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".keystore", ".jks")


@dataclass
class PathSandbox:
    roots: list[Path]
    blocked: list[Path] = field(default_factory=list)
    default_dir: Path | None = None

    def __post_init__(self) -> None:
        self.roots = [r.expanduser().resolve() for r in self.roots]
        self.blocked = [b.expanduser().resolve() for b in self.blocked]
        if self.default_dir is None and self.roots:
            self.default_dir = self.roots[0]

    def resolve(self, raw: str | os.PathLike[str]) -> Path:
        """Resolve um caminho (relativo à pasta de trabalho) e valida o acesso."""
        if raw is None or str(raw).strip() == "":
            raw = "."
        candidate = Path(str(raw).strip()).expanduser()
        if not candidate.is_absolute():
            base = self.default_dir or Path.cwd()
            candidate = base / candidate
        resolved = candidate.resolve()  # segue links simbólicos e remove ".."
        for blocked in self.blocked:
            if resolved == blocked or resolved.is_relative_to(blocked):
                raise GuardError("Acesso negado: área protegida do sistema da Sexta-Feira.")
        if not any(resolved == root or resolved.is_relative_to(root) for root in self.roots):
            allowed = "; ".join(str(r) for r in self.roots)
            raise GuardError(
                f"Acesso negado: '{resolved}' está fora das pastas liberadas ({allowed}). "
                "O usuário pode liberar novas pastas nas Configurações."
            )
        for part in resolved.parts:
            lowered = part.lower()
            if lowered in SENSITIVE_NAMES or lowered.startswith(".env."):
                raise GuardError(f"Acesso negado: '{part}' pode conter credenciais.")
        if resolved.suffix.lower() in SENSITIVE_SUFFIXES:
            raise GuardError("Acesso negado: arquivos de chaves/certificados são protegidos.")
        return resolved


# --------------------------------------------------------------------------
# Comandos de terminal
# --------------------------------------------------------------------------

_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (
        r"\brm\s+(-[a-z]*\s+)*-[a-z]*(r[a-z]*f|f[a-z]*r)[a-z]*\s+(--no-preserve-root\s+)?(/|~|\$home|/\*|\*|\.\*?)(\s|$)",
        "apagar recursivamente a raiz, a pasta pessoal ou tudo",
    ),
    (r"--no-preserve-root", "remoção da raiz do sistema"),
    (r"\bmkfs(\.\w+)?\b", "formatar disco"),
    (r"\bdd\b[^|;&]*\bof=/dev/", "escrever diretamente em um disco"),
    (r">\s*/dev/(sd[a-z]|nvme|hd[a-z]|disk)", "sobrescrever um disco"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bformat(\.com)?\s+[a-z]:", "formatar unidade"),
    (r"\bdiskpart\b", "particionamento de disco"),
    (r"\bcipher\s+/w", "apagar dados livres do disco"),
    (r"\bvssadmin\b.*\bdelete\b", "apagar cópias de sombra (padrão de ransomware)"),
    (r"\bbcdedit\b", "alterar a inicialização do sistema"),
    (r"\breg(\.exe)?\s+delete\s+hk(lm|ey_local_machine)", "apagar chaves do registro do sistema"),
    (r"\bchmod\s+(-[a-z]+\s+)*0?777\s+/(\s|$)", "permissões totais na raiz"),
    (r"\bchown\s+-r\b.*\s/(\s|$)", "mudar dono da raiz"),
    (r"remove-item\b.*-recurse\b.*\s[a-z]:\\?\s*$", "apagar uma unidade inteira"),
    (r"(sexta\.db|\.sexta-feira)", "acessar a área protegida da Sexta-Feira"),
]

_CRITICAL_PATTERNS: list[tuple[str, str]] = [
    (r"\b(rm|rmdir|del|erase|rd|shred|unlink)\b", "exclusão de arquivos"),
    (r"\bremove-item\b|\bri\b\s", "exclusão de arquivos"),
    (r"\b(kill|killall|pkill|taskkill)\b|\bstop-process\b", "encerramento de processos"),
    (r"\b(shutdown|reboot|halt|poweroff)\b|\brestart-computer\b|\bstop-computer\b", "desligar/reiniciar"),
    (r"\b(sudo|su|doas|runas)\b", "privilégios de administrador"),
    (r"\b(chmod|chown|icacls|takeown)\b", "alteração de permissões"),
    (r"\bgit\s+push\b.*(--force|-f\b)", "git push forçado"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f)", "descartar alterações do git"),
    (r"\b(pip|pip3|npm|pnpm|yarn|choco|winget|brew)\s+(uninstall|remove)\b", "desinstalar pacotes"),
    (r"\b(apt|apt-get|dnf|yum|pacman)\s+(remove|purge|-r)\b", "desinstalar pacotes do sistema"),
    (r"\b(curl|wget|iwr|invoke-webrequest)\b.*\|\s*(sh|bash|zsh|iex|python)", "executar script baixado da internet"),
    (r"\binvoke-expression\b|\biex\b", "execução dinâmica de código"),
    (r"\b(crontab\s+-r|schtasks\s+/delete)\b", "apagar tarefas agendadas"),
    (r"\bsystemctl\s+(stop|disable|mask)\b|\bsc\s+(stop|delete)\b", "parar serviços do sistema"),
    (r"\btruncate\b|\bmv\b.*\s/dev/null", "apagar conteúdo"),
    (r"\b(netsh|iptables|ufw)\b", "alterar firewall/rede"),
    (r"\bsetx?\b\s+\w*path\b", "alterar variáveis de ambiente do sistema"),
]


@dataclass(frozen=True)
class CommandAssessment:
    risk: Risk
    blocked_reason: str | None = None
    flags: tuple[str, ...] = ()


_RM_FORBIDDEN_TARGETS = {
    "/",
    "/*",
    "~",
    "~/",
    "~/*",
    "$home",
    "$home/",
    "${home}",
    "*",
    ".",
    "./",
    "./*",
    "..",
    "../",
    "c:",
    "c:\\",
    "c:/",
    "%userprofile%",
}


def _is_catastrophic_rm(text: str) -> bool:
    if not re.search(r"\b(rm|rd|rmdir|del|remove-item)\b", text):
        return False
    tokens = text.replace(";", " ; ").replace("&&", " && ").split()
    recursive = any(
        (t.startswith("-") and not t.startswith("--") and "r" in t) or t in ("--recursive", "/s", "-recurse")
        for t in tokens
    )
    return recursive and any(t.strip("'\"") in _RM_FORBIDDEN_TARGETS for t in tokens)


def classify_command(command: str, *, protected_paths: list[str] | None = None) -> CommandAssessment:
    text = command.strip().lower()
    if not text:
        return CommandAssessment(Risk.EXEC, blocked_reason="comando vazio")
    if _is_catastrophic_rm(text):
        return CommandAssessment(Risk.CRITICAL, blocked_reason="apagar recursivamente a raiz, a pasta pessoal ou tudo")
    for protected in protected_paths or []:
        if protected and protected.lower() in text:
            return CommandAssessment(Risk.CRITICAL, blocked_reason="acessar a área protegida da Sexta-Feira")
    for pattern, reason in _BLOCKED_PATTERNS:
        if re.search(pattern, text):
            return CommandAssessment(Risk.CRITICAL, blocked_reason=reason)
    flags = tuple(reason for pattern, reason in _CRITICAL_PATTERNS if re.search(pattern, text))
    if flags:
        return CommandAssessment(Risk.CRITICAL, flags=tuple(dict.fromkeys(flags)))
    return CommandAssessment(Risk.EXEC)


# --------------------------------------------------------------------------
# Segredos
# --------------------------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|senha|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
]

_SENSITIVE_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|SESSION|COOKIE)", re.I)


class SecretRedactor:
    def __init__(self, known_secrets: list[str] | None = None):
        self._known = [s for s in (known_secrets or []) if s and len(s) >= 8]

    def __call__(self, text: str) -> str:
        for secret in self._known:
            text = text.replace(secret, "[SEGREDO REMOVIDO]")
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub("[SEGREDO REMOVIDO]", text)
        return text


def safe_env() -> dict[str, str]:
    """Ambiente para subprocessos sem variáveis que pareçam credenciais."""
    return {
        k: v
        for k, v in os.environ.items()
        if not _SENSITIVE_ENV.search(k) and not k.upper().startswith(("ANTHROPIC_", "SEXTA_"))
    }
