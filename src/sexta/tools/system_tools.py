"""Ferramentas de sistema: terminal, informações, processos e abertura de programas."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from typing import Literal

import psutil
from pydantic import BaseModel, Field

from ..security.guards import classify_command, safe_env
from ..security.permissions import Risk
from .base import Assessment, Tool, ToolContext, ToolOutput

# --- shell_run -------------------------------------------------------------


class ShellRunArgs(BaseModel):
    command: str = Field(min_length=1, max_length=4000, description="Comando a executar no terminal do sistema.")
    cwd: str = Field(default=".", description="Pasta de execução (dentro das pastas liberadas).")
    timeout_s: int = Field(default=60, ge=1, le=600, description="Tempo máximo em segundos.")


def _assess_shell(args: ShellRunArgs, ctx: ToolContext) -> Assessment:
    cwd = ctx.sandbox.resolve(args.cwd)
    verdict = classify_command(args.command, protected_paths=[str(ctx.settings.data_dir)])
    summary = f"Executar no terminal: {args.command}"
    if verdict.flags:
        summary += f"  ⚠ {', '.join(verdict.flags)}"
    return Assessment(
        verdict.risk,
        summary=summary,
        blocked_reason=verdict.blocked_reason,
        details={"cwd": str(cwd), "shell": _shell_name()},
    )


def _shell_name() -> str:
    return "cmd.exe" if os.name == "nt" else os.environ.get("SHELL", "/bin/sh")


def _run_sync(command: str, cwd: str, timeout: int) -> dict:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=safe_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return {
            "codigo_saida": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-6000:],
            "duracao_s": round(time.perf_counter() - started, 2),
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return {"erro": f"tempo limite de {timeout}s excedido; processo encerrado", "stdout": out[-6000:]}


async def shell_run(args: ShellRunArgs, ctx: ToolContext):
    cwd = ctx.sandbox.resolve(args.cwd)
    if not cwd.is_dir():
        return ToolOutput(f"Pasta de execução não existe: {cwd}", is_error=True)
    result = await asyncio.to_thread(_run_sync, args.command, str(cwd), args.timeout_s)
    if "erro" in result:
        return ToolOutput(str(result), is_error=True, data=result)
    return result


# --- system_info -----------------------------------------------------------


class NoArgs(BaseModel):
    pass


def system_snapshot(workspace: str | None = None) -> dict:
    vm = psutil.virtual_memory()
    disk_path = workspace if workspace and os.path.exists(workspace) else os.path.abspath(os.sep)
    disk = psutil.disk_usage(disk_path)
    battery = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery = {"percentual": round(b.percent), "carregando": b.power_plugged}
    except (AttributeError, NotImplementedError):
        battery = None
    return {
        "sistema": f"{platform.system()} {platform.release()}",
        "maquina": platform.machine(),
        "python": sys.version.split()[0],
        "cpu_percentual": psutil.cpu_percent(interval=None),
        "cpu_nucleos": psutil.cpu_count(logical=True),
        "memoria_percentual": vm.percent,
        "memoria_total_gb": round(vm.total / 1024**3, 1),
        "memoria_disponivel_gb": round(vm.available / 1024**3, 1),
        "disco_percentual": disk.percent,
        "disco_livre_gb": round(disk.free / 1024**3, 1),
        "ligado_desde": time.strftime("%Y-%m-%d %H:%M", time.localtime(psutil.boot_time())),
        "bateria": battery,
    }


async def system_info(args: NoArgs, ctx: ToolContext):
    return await asyncio.to_thread(system_snapshot, str(ctx.settings.workspace_dir))


# --- process_list ----------------------------------------------------------


class ProcessListArgs(BaseModel):
    sort_by: Literal["cpu", "memory"] = "memory"
    name_filter: str | None = Field(default=None, description="Filtrar por parte do nome.")
    limit: int = Field(default=15, ge=1, le=100)


def _list_processes(args: ProcessListArgs) -> list[dict]:
    items = []
    for proc in psutil.process_iter(["pid", "name", "username", "memory_info", "cpu_percent", "status"]):
        info = proc.info
        name = info.get("name") or ""
        if args.name_filter and args.name_filter.lower() not in name.lower():
            continue
        mem = info.get("memory_info")
        items.append(
            {
                "pid": info["pid"],
                "nome": name,
                "cpu_percentual": info.get("cpu_percent") or 0.0,
                "memoria_mb": round(mem.rss / 1024**2, 1) if mem else 0.0,
                "status": info.get("status"),
            }
        )
    key = "cpu_percentual" if args.sort_by == "cpu" else "memoria_mb"
    items.sort(key=lambda i: i[key], reverse=True)
    return items[: args.limit]


async def process_list(args: ProcessListArgs, ctx: ToolContext):
    return await asyncio.to_thread(_list_processes, args)


# --- process_kill ----------------------------------------------------------


class ProcessKillArgs(BaseModel):
    pid: int = Field(gt=0, description="PID do processo a encerrar.")
    force: bool = Field(default=False, description="Forçar (kill) em vez de pedir para encerrar (terminate).")


_PROTECTED_PROCESS_NAMES = {
    "system",
    "init",
    "systemd",
    "launchd",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "lsass.exe",
    "services.exe",
    "smss.exe",
    "explorer.exe",
    "kernel_task",
}


def _assess_kill(args: ProcessKillArgs, ctx: ToolContext) -> Assessment:
    try:
        proc = psutil.Process(args.pid)
        name = proc.name()
    except psutil.Error:
        return Assessment(
            Risk.CRITICAL,
            summary=f"Encerrar processo {args.pid}",
            blocked_reason="processo não encontrado ou inacessível",
        )
    own = {os.getpid(), os.getppid()}
    if args.pid in own or args.pid <= 4 or name.lower() in _PROTECTED_PROCESS_NAMES:
        return Assessment(
            Risk.CRITICAL,
            summary=f"Encerrar {name} ({args.pid})",
            blocked_reason="processo essencial do sistema ou da própria Sexta-Feira",
        )
    action = "Forçar encerramento de" if args.force else "Encerrar"
    return Assessment(Risk.CRITICAL, summary=f"{action} {name} (PID {args.pid})")


async def process_kill(args: ProcessKillArgs, ctx: ToolContext):
    def _kill() -> str:
        proc = psutil.Process(args.pid)
        name = proc.name()
        if args.force:
            proc.kill()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
            return f"Processo {name} ({args.pid}) encerrado."
        except psutil.TimeoutExpired:
            return f"Sinal enviado para {name} ({args.pid}), mas ele ainda não terminou."

    try:
        return await asyncio.to_thread(_kill)
    except psutil.NoSuchProcess:
        return ToolOutput(f"O processo {args.pid} não existe mais.", is_error=True)
    except psutil.AccessDenied:
        return ToolOutput(f"Sem permissão para encerrar o processo {args.pid}.", is_error=True)


# --- app_open --------------------------------------------------------------


class AppOpenArgs(BaseModel):
    target: str = Field(
        min_length=1,
        max_length=1000,
        description="Link (https://...), arquivo/pasta dentro das pastas liberadas, ou nome de um programa (ex.: 'notepad', 'code', 'calc').",
    )


def _classify_target(target: str, ctx: ToolContext) -> tuple[str, str]:
    lowered = target.strip().lower()
    if lowered.startswith(("http://", "https://")):
        return "url", target.strip()
    if any(sep in target for sep in ("/", "\\")) or target.startswith("."):
        return "path", str(ctx.sandbox.resolve(target))
    return "app", target.strip()


def _assess_open(args: AppOpenArgs, ctx: ToolContext) -> Assessment:
    kind, value = _classify_target(args.target, ctx)
    label = {"url": "Abrir o link", "path": "Abrir", "app": "Abrir o programa"}[kind]
    blocked = None
    if kind == "app" and any(ch in value for ch in "&|;$`<>\"'"):
        blocked = "nome de programa inválido"
    return Assessment(Risk.EXEC, summary=f"{label} {value}", blocked_reason=blocked)


def _open_sync(kind: str, value: str) -> str:
    if kind == "url":
        webbrowser.open(value)
        return f"Link aberto no navegador: {value}"
    system = platform.system()
    if system == "Windows":
        os.startfile(value)  # type: ignore[attr-defined]  # noqa: S606
    elif system == "Darwin":
        cmd = ["open", value] if kind == "path" else ["open", "-a", value]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if kind == "path":
            subprocess.Popen(["xdg-open", value], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            exe = shutil.which(value)
            if not exe:
                raise FileNotFoundError(f"programa '{value}' não encontrado no PATH")
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return f"Aberto: {value}"


async def app_open(args: AppOpenArgs, ctx: ToolContext):
    kind, value = _classify_target(args.target, ctx)
    return await asyncio.to_thread(_open_sync, kind, value)


TOOLS = [
    Tool(
        "shell_run",
        "Executa um comando no terminal (cmd no Windows, shell no Linux/macOS) e retorna a saída. Comandos destrutivos exigem confirmação; alguns são sempre bloqueados.",
        ShellRunArgs,
        "shell.exec",
        Risk.EXEC,
        shell_run,
        _assess_shell,
        timeout_s=620,
    ),
    Tool(
        "system_info",
        "Mostra informações do computador: sistema, CPU, memória, disco, bateria.",
        NoArgs,
        "system.read",
        Risk.READ,
        system_info,
    ),
    Tool(
        "process_list",
        "Lista os processos em execução (ordenados por memória ou CPU).",
        ProcessListArgs,
        "system.read",
        Risk.READ,
        process_list,
    ),
    Tool(
        "process_kill",
        "Encerra um processo pelo PID (sempre pede confirmação).",
        ProcessKillArgs,
        "process.control",
        Risk.CRITICAL,
        process_kill,
        _assess_kill,
    ),
    Tool(
        "app_open",
        "Abre um programa, um arquivo/pasta com o aplicativo padrão, ou um link no navegador.",
        AppOpenArgs,
        "apps.launch",
        Risk.EXEC,
        app_open,
        _assess_open,
    ),
]
