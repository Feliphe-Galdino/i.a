"""Ferramentas disponíveis para a Sexta-Feira."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolOutput, ToolRegistry


def build_default_registry() -> ToolRegistry:
    from . import fs_tools, memory_tools, system_tools

    return ToolRegistry([*memory_tools.TOOLS, *fs_tools.TOOLS, *system_tools.TOOLS])


__all__ = ["Tool", "ToolContext", "ToolOutput", "ToolRegistry", "build_default_registry"]
