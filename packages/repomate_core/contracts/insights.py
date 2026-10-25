"""Orientation and test-guidance insights attached to every run.

These answer the PS04 background directly: help a newcomer understand an
unfamiliar repository, and tell them which tests matter for this issue —
without overstating what was verified.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class KeyPath(BaseModel):
    path: str
    role: str


class Orientation(BaseModel):
    """Snapshot-derived repository map for a newcomer."""

    summary: str
    key_paths: list[KeyPath] = []
    languages: dict[str, float] = {}
    entry_points: list[KeyPath] = []
    generated_by: str = "snapshot-v1"


class RelevantTest(BaseModel):
    path: str
    reason: str


class TestGuidance(BaseModel):
    """Which tests to run for this task, and what actually ran."""

    run_command: Optional[str] = None
    focused_command: Optional[str] = None
    relevant_tests: list[RelevantTest] = []
    note: str = ""
