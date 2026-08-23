from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_poetry_toolchain import (
    PoetryToolchainError,
    bootstrap_version,
    lock_generator_version,
    required_version,
)

REPO = Path(__file__).resolve().parents[2]


def test_every_poetry_surface_uses_the_project_pin() -> None:
    wanted = required_version((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    lock_version = lock_generator_version(
        (REPO / "poetry.lock").read_text(encoding="utf-8")
    )
    bootstrap = bootstrap_version(
        (REPO / ".github" / "bootstrap" / "poetry-requirements-py312.txt").read_text(
            encoding="utf-8"
        )
    )

    assert wanted == "2.4.1"
    assert lock_version == wanted
    assert bootstrap == wanted


def test_a_range_cannot_become_the_build_tool_source() -> None:
    with pytest.raises(PoetryToolchainError):
        required_version(
            """
[tool.poetry]
requires-poetry = "^2.4"
"""
        )
