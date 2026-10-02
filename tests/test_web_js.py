"""Executa os testes JavaScript da interface (tests/js) se o Node.js estiver instalado."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
JS_TESTS = sorted(str(p) for p in (Path(__file__).parent / "js").glob("*.test.mjs"))


@pytest.mark.skipif(NODE is None, reason="Node.js não instalado (opcional)")
def test_javascript_suite():
    result = subprocess.run([NODE, "--test", *JS_TESTS], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
