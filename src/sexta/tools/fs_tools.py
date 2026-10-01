"""Ferramentas de arquivos — sempre dentro das pastas liberadas (sandbox).

Segurança extra:
* sobrescrever um arquivo guarda a versão anterior na lixeira;
* "excluir" move para a lixeira (``~/.sexta-feira/lixeira``), nunca apaga de vez.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..security.permissions import Risk
from .base import Assessment, Tool, ToolContext, ToolOutput

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
}
MAX_READ_BYTES = 2_000_000
MAX_SEARCH_FILES = 3_000


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample[:4096]


def _move_to_trash(path: Path, ctx: ToolContext) -> Path:
    trash = ctx.settings.trash_dir
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = trash / f"{stamp}__{path.name}"
    counter = 1
    while target.exists():
        target = trash / f"{stamp}__{counter}__{path.name}"
        counter += 1
    shutil.move(str(path), str(target))
    return target


# --- fs_list ---------------------------------------------------------------


class FsListArgs(BaseModel):
    path: str = Field(default=".", description="Pasta a listar (relativa à pasta de trabalho ou absoluta).")
    pattern: str | None = Field(default=None, description="Filtro estilo glob, ex.: '*.py'.")
    max_entries: int = Field(default=200, ge=1, le=1000)


def _assess_list(args: FsListArgs, ctx: ToolContext) -> Assessment:
    path = ctx.sandbox.resolve(args.path)
    return Assessment(Risk.READ, summary=f"Listar a pasta {path}")


async def fs_list(args: FsListArgs, ctx: ToolContext):
    path = ctx.sandbox.resolve(args.path)
    if not path.exists():
        return ToolOutput(f"A pasta não existe: {path}", is_error=True)
    if not path.is_dir():
        return ToolOutput(f"Não é uma pasta: {path}", is_error=True)
    entries = []
    for entry in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if args.pattern and not fnmatch.fnmatch(entry.name.lower(), args.pattern.lower()):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        entries.append(
            {
                "nome": entry.name + ("/" if entry.is_dir() else ""),
                "tamanho": None if entry.is_dir() else stat.st_size,
                "modificado": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="minutes"),
            }
        )
        if len(entries) >= args.max_entries:
            break
    return {"pasta": str(path), "itens": entries, "total_listado": len(entries)}


# --- fs_read ---------------------------------------------------------------


class FsReadArgs(BaseModel):
    path: str = Field(description="Arquivo de texto a ler.")
    start_line: int = Field(default=1, ge=1, description="Primeira linha (1 = início).")
    max_lines: int = Field(default=400, ge=1, le=5000)


def _assess_read(args: FsReadArgs, ctx: ToolContext) -> Assessment:
    path = ctx.sandbox.resolve(args.path)
    return Assessment(Risk.READ, summary=f"Ler o arquivo {path}")


async def fs_read(args: FsReadArgs, ctx: ToolContext):
    path = ctx.sandbox.resolve(args.path)
    if not path.is_file():
        return ToolOutput(f"Arquivo não encontrado: {path}", is_error=True)
    if path.stat().st_size > MAX_READ_BYTES:
        return ToolOutput(f"Arquivo grande demais para leitura direta ({path.stat().st_size} bytes).", is_error=True)
    raw = await asyncio.to_thread(path.read_bytes)
    if _is_binary(raw):
        return ToolOutput("O arquivo parece ser binário; só leio arquivos de texto.", is_error=True)
    lines = raw.decode("utf-8", errors="replace").splitlines()
    start = args.start_line - 1
    chunk = lines[start : start + args.max_lines]
    numbered = "\n".join(f"{i + args.start_line:>5} | {line}" for i, line in enumerate(chunk))
    remaining = max(0, len(lines) - (start + len(chunk)))
    footer = f"\n[... mais {remaining} linhas; use start_line={start + len(chunk) + 1}]" if remaining else ""
    return f'<arquivo caminho="{path}" linhas="{len(lines)}">\n{numbered}\n</arquivo>{footer}'


# --- fs_write --------------------------------------------------------------


class FsWriteArgs(BaseModel):
    path: str = Field(description="Arquivo a criar ou alterar.")
    content: str = Field(description="Conteúdo de texto completo a gravar.")
    mode: Literal["create", "overwrite", "append"] = Field(
        default="create",
        description="create: só cria se não existir; overwrite: substitui (versão anterior vai para a lixeira); append: acrescenta ao final.",
    )


def _assess_write(args: FsWriteArgs, ctx: ToolContext) -> Assessment:
    path = ctx.sandbox.resolve(args.path)
    exists = path.exists()
    verb = {"create": "Criar", "overwrite": "Substituir" if exists else "Criar", "append": "Acrescentar texto em"}[
        args.mode
    ]
    preview = args.content[:600] + ("…" if len(args.content) > 600 else "")
    return Assessment(
        Risk.WRITE,
        summary=f"{verb} {path} ({len(args.content)} caracteres)",
        details={"preview": preview, "exists": exists},
    )


async def fs_write(args: FsWriteArgs, ctx: ToolContext):
    path = ctx.sandbox.resolve(args.path)
    if path.is_dir():
        return ToolOutput(f"{path} é uma pasta.", is_error=True)
    if args.mode == "create" and path.exists():
        return ToolOutput(f"O arquivo já existe: {path}. Use mode='overwrite' ou 'append'.", is_error=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if args.mode == "overwrite" and path.exists():
        ctx.settings.trash_dir.mkdir(parents=True, exist_ok=True)
        backup = await asyncio.to_thread(
            shutil.copy2, path, ctx.settings.trash_dir / f"{datetime.now():%Y%m%d-%H%M%S}__{path.name}"
        )
    if args.mode == "append":

        def _append() -> None:
            with path.open("a", encoding="utf-8", newline="") as fh:
                fh.write(args.content)

        await asyncio.to_thread(_append)
    else:
        await asyncio.to_thread(path.write_text, args.content, encoding="utf-8", newline="")
    message = f"Arquivo gravado: {path} ({len(args.content)} caracteres, modo {args.mode})."
    if backup:
        message += f" Versão anterior salva em {backup}."
    return message


# --- fs_search -------------------------------------------------------------


class FsSearchArgs(BaseModel):
    query: str = Field(min_length=1, description="Texto a procurar dentro dos arquivos (sem diferenciar maiúsculas).")
    path: str = Field(default=".", description="Pasta onde procurar.")
    glob: str = Field(default="*", description="Filtro de nome de arquivo, ex.: '*.md'.")
    max_results: int = Field(default=50, ge=1, le=300)


def _assess_search(args: FsSearchArgs, ctx: ToolContext) -> Assessment:
    path = ctx.sandbox.resolve(args.path)
    return Assessment(Risk.READ, summary=f"Procurar “{args.query}” em {path}")


def _search_sync(root: Path, args: FsSearchArgs, ctx: ToolContext) -> dict:
    needle = args.query.lower()
    results: list[dict] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not fnmatch.fnmatch(filename.lower(), args.glob.lower()):
                continue
            file_path = Path(dirpath) / filename
            try:
                ctx.sandbox.resolve(file_path)
                if file_path.stat().st_size > MAX_READ_BYTES:
                    continue
                data = file_path.read_bytes()
            except Exception:  # noqa: BLE001 — arquivos protegidos/ilegíveis são ignorados
                continue
            scanned += 1
            if _is_binary(data):
                continue
            name_hit = needle in filename.lower()
            for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
                if needle in line.lower():
                    results.append({"arquivo": str(file_path), "linha": number, "trecho": line.strip()[:200]})
                    if len(results) >= args.max_results:
                        return {"resultados": results, "arquivos_verificados": scanned, "truncado": True}
            if name_hit and not any(r["arquivo"] == str(file_path) for r in results):
                results.append({"arquivo": str(file_path), "linha": None, "trecho": "(nome do arquivo)"})
            if scanned >= MAX_SEARCH_FILES:
                return {"resultados": results, "arquivos_verificados": scanned, "truncado": True}
    return {"resultados": results, "arquivos_verificados": scanned, "truncado": False}


async def fs_search(args: FsSearchArgs, ctx: ToolContext):
    root = ctx.sandbox.resolve(args.path)
    if not root.is_dir():
        return ToolOutput(f"Pasta não encontrada: {root}", is_error=True)
    return await asyncio.to_thread(_search_sync, root, args, ctx)


# --- fs_move ---------------------------------------------------------------


class FsMoveArgs(BaseModel):
    source: str = Field(description="Arquivo ou pasta de origem.")
    destination: str = Field(description="Novo caminho (ou pasta de destino existente).")


def _assess_move(args: FsMoveArgs, ctx: ToolContext) -> Assessment:
    src = ctx.sandbox.resolve(args.source)
    dst = ctx.sandbox.resolve(args.destination)
    return Assessment(Risk.WRITE, summary=f"Mover/renomear {src} → {dst}")


async def fs_move(args: FsMoveArgs, ctx: ToolContext):
    src = ctx.sandbox.resolve(args.source)
    dst = ctx.sandbox.resolve(args.destination)
    if not src.exists():
        return ToolOutput(f"Origem não encontrada: {src}", is_error=True)
    if dst.is_dir():
        dst = dst / src.name
        ctx.sandbox.resolve(dst)
    if dst.exists():
        return ToolOutput(f"O destino já existe: {dst}. Escolha outro nome.", is_error=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.move, str(src), str(dst))
    return f"Movido: {src} → {dst}"


# --- fs_delete -------------------------------------------------------------


class FsDeleteArgs(BaseModel):
    path: str = Field(description="Arquivo ou pasta a excluir (vai para a lixeira da Sexta-Feira).")


def _assess_delete(args: FsDeleteArgs, ctx: ToolContext) -> Assessment:
    path = ctx.sandbox.resolve(args.path)
    if path in ctx.sandbox.roots:
        return Assessment(
            Risk.CRITICAL, summary=f"Excluir {path}", blocked_reason="não é permitido excluir uma pasta raiz liberada"
        )
    kind = "a pasta" if path.is_dir() else "o arquivo"
    return Assessment(Risk.CRITICAL, summary=f"Mover para a lixeira {kind} {path}")


async def fs_delete(args: FsDeleteArgs, ctx: ToolContext):
    path = ctx.sandbox.resolve(args.path)
    if not path.exists():
        return ToolOutput(f"Não encontrado: {path}", is_error=True)
    target = await asyncio.to_thread(_move_to_trash, path, ctx)
    return f"{path} foi movido para a lixeira ({target}). Pode ser restaurado manualmente."


TOOLS = [
    Tool(
        "fs_list",
        "Lista arquivos e pastas de um diretório liberado.",
        FsListArgs,
        "fs.read",
        Risk.READ,
        fs_list,
        _assess_list,
    ),
    Tool(
        "fs_read",
        "Lê um arquivo de texto (com números de linha). Para arquivos longos, leia em partes.",
        FsReadArgs,
        "fs.read",
        Risk.READ,
        fs_read,
        _assess_read,
    ),
    Tool(
        "fs_write",
        "Cria ou altera um arquivo de texto. Sobrescrever guarda a versão anterior na lixeira.",
        FsWriteArgs,
        "fs.write",
        Risk.WRITE,
        fs_write,
        _assess_write,
    ),
    Tool(
        "fs_search",
        "Procura um texto dentro dos arquivos de uma pasta (ignora .git, node_modules, .venv).",
        FsSearchArgs,
        "fs.read",
        Risk.READ,
        fs_search,
        _assess_search,
    ),
    Tool(
        "fs_move",
        "Move ou renomeia um arquivo/pasta (para organizar arquivos).",
        FsMoveArgs,
        "fs.write",
        Risk.WRITE,
        fs_move,
        _assess_move,
    ),
    Tool(
        "fs_delete",
        "Exclui um arquivo ou pasta movendo para a lixeira (sempre pede confirmação).",
        FsDeleteArgs,
        "fs.delete",
        Risk.CRITICAL,
        fs_delete,
        _assess_delete,
    ),
]
