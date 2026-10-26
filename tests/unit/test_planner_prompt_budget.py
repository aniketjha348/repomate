"""Planner prompt budget and gateway retry budget.

Two production failures motivated these:

- The planner prompt was large enough that a gateway behind a ~100s edge
  timeout returned Cloudflare 524 (origin timeout) instead of a plan. The
  prompt is therefore bounded, and the bound is tunable.
- Two retries were too few for a 524, which means "the origin is still
  working". The retry budget is now tunable and capped.
"""

from __future__ import annotations

import os

import httpx
import pytest

from repomate_core.contracts import (
    EvidenceRecord,
    EvidenceKind,
    LicenseInfo,
    LicenseStatus,
    RepositorySnapshot,
)
from repomate_core.models import ModelError, OpenAIProvider
from repomate_core.models.openai import model_retries_from_env
from repomate_core.planning.model_planner import _build_context, user_payload

KEY = "sk-test"


def _snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        owner="acme",
        name="fixture",
        url="https://github.com/acme/fixture",
        commit_sha="a" * 40,
        default_branch="main",
        license=LicenseInfo(status=LicenseStatus.RECOGNIZED, spdx_id="MIT"),
    )


def _evidence(count: int, snippet_chars: int = 4000) -> list[EvidenceRecord]:
    # ``EvidenceRecord.snippet`` is contract-capped at 4000 chars, so the
    # fixture stays inside it; the planner's own bound is much tighter.
    return [
        EvidenceRecord(
            id=f"ev{i}",
            kind=EvidenceKind.DOC,
            path=f"docs/file{i}.md",
            start_line=1,
            end_line=10,
            snippet="x" * snippet_chars,
            rationale="matches task keywords",
        )
        for i in range(1, count + 1)
    ]


class TestPromptBudget:
    def test_snippets_are_bounded(self, monkeypatch):
        monkeypatch.delenv("REPOMATE_PLANNER_SNIPPET_CHARS", raising=False)
        context = _build_context("document it", _snapshot(), _evidence(3))

        assert all(len(e["snippet"]) <= 600 for e in context["evidence"])

    def test_evidence_record_count_is_bounded(self, monkeypatch):
        monkeypatch.delenv("REPOMATE_PLANNER_MAX_EVIDENCE", raising=False)
        context = _build_context("document it", _snapshot(), _evidence(12))

        assert len(context["evidence"]) == 6

    def test_snippet_budget_is_tunable(self, monkeypatch):
        monkeypatch.setenv("REPOMATE_PLANNER_SNIPPET_CHARS", "1500")
        context = _build_context("document it", _snapshot(), _evidence(2))

        assert all(len(e["snippet"]) == 1500 for e in context["evidence"])

    def test_budget_is_clamped_to_a_sane_range(self, monkeypatch):
        monkeypatch.setenv("REPOMATE_PLANNER_SNIPPET_CHARS", "999999")
        context = _build_context("document it", _snapshot(), _evidence(1))
        assert len(context["evidence"][0]["snippet"]) == 4000

        monkeypatch.setenv("REPOMATE_PLANNER_SNIPPET_CHARS", "1")
        context = _build_context("document it", _snapshot(), _evidence(1))
        assert len(context["evidence"][0]["snippet"]) == 200

    def test_garbage_env_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("REPOMATE_PLANNER_SNIPPET_CHARS", "not-a-number")
        context = _build_context("document it", _snapshot(), _evidence(1))
        assert len(context["evidence"][0]["snippet"]) == 600

    def test_payload_stays_small_for_a_full_evidence_set(self, monkeypatch):
        monkeypatch.delenv("REPOMATE_PLANNER_SNIPPET_CHARS", raising=False)
        monkeypatch.delenv("REPOMATE_PLANNER_MAX_EVIDENCE", raising=False)
        # 8 records of 4k chars each would previously have shipped ~8k chars
        # of snippet; the bound keeps the whole prompt well under that.
        payload = user_payload("document it", _snapshot(), _evidence(8))
        assert len(payload) < 6000


class TestRetryBudget:
    def test_default_is_two_retries(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_MAX_RETRIES", raising=False)
        assert model_retries_from_env() == 2

    def test_tunable(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MAX_RETRIES", "4")
        assert model_retries_from_env() == 4

    def test_capped(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MAX_RETRIES", "99")
        assert model_retries_from_env() == 6

    def test_garbage_falls_back(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MAX_RETRIES", "lots")
        assert model_retries_from_env() == 2

    def test_524_is_retried_within_the_configured_budget(self):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            return httpx.Response(524, text="origin timeout")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = OpenAIProvider(
            KEY, base_url="https://gateway.test/v1", client=client, max_retries=4
        )
        with pytest.raises(ModelError, match="524"):
            provider.complete(system="s", user="u")
        assert len(attempts) == 5  # initial + 4 retries

    def test_zero_retries_means_one_attempt(self):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            return httpx.Response(503, text="down")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = OpenAIProvider(
            KEY, base_url="https://gateway.test/v1", client=client, max_retries=0
        )
        with pytest.raises(ModelError):
            provider.complete(system="s", user="u")
        assert len(attempts) == 1

    def test_524_recovers_when_a_later_attempt_succeeds(self):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            if len(attempts) < 3:
                return httpx.Response(524, text="origin timeout")
            return httpx.Response(
                200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = OpenAIProvider(
            KEY, base_url="https://gateway.test/v1", client=client, max_retries=3
        )
        result = provider.complete(system="s", user="u")
        assert "ok" in result.text
        assert len(attempts) == 3
