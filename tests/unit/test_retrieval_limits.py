"""Explicit retrieval budgets and the PARTIAL report they produce."""

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from repomate_core.contracts import (
    RetrievalLimit,
    RetrievalLimitHit,
    RetrievalLimits,
    RetrievalReport,
    RetrievalStatus,
)
from repomate_core.evidence.collector import collect_evidence_with_report
from repomate_core.repository.inspect import inspect_repository
from repomate_core.repository.workspace import RepoWorkspace


def _git(cwd: Path, *args: str) -> None:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="T",
        GIT_AUTHOR_EMAIL="t@t.invalid",
        GIT_COMMITTER_NAME="T",
        GIT_COMMITTER_EMAIL="t@t.invalid",
    )
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert result.returncode == 0, result.stderr


def _repo(tmp_path: Path, files: dict[str, str]) -> RepoWorkspace:
    root = tmp_path / "retrieval-repo"
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    _git(root, "init", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "retrieval fixture")
    return RepoWorkspace.from_local(root)


def _snapshot(ws: RepoWorkspace):
    return inspect_repository(
        ws, owner="acme", name="retrieval", url="https://github.com/acme/retrieval"
    )


MATCHING_FILES = {
    "README.md": "# Retrieval fixture\n\nThe widget option is documented here.\n",
    "docs/guide.md": "# Guide\n\nConfigure the widget option.\n",
    "src/widget.py": "def widget():\n    return 'widget option'\n",
}


def _collect(ws: RepoWorkspace, limits: RetrievalLimits):
    return collect_evidence_with_report(
        ws, _snapshot(ws), "document the widget option", limits=limits
    )


class TestRetrievalReportContract:
    def _report(self, status: RetrievalStatus, hits, summary: str) -> RetrievalReport:
        return RetrievalReport(
            status=status,
            limits=RetrievalLimits(),
            files_total=2,
            files_eligible=2,
            files_examined=1,
            bytes_read=10,
            search_results=1,
            evidence_records=1,
            elapsed_ms=5,
            limit_hits=hits,
            summary=summary,
        )

    def _hit(self) -> RetrievalLimitHit:
        return RetrievalLimitHit(
            limit=RetrievalLimit.MAX_FILES,
            allowed=1,
            observed=2,
            remaining_work="1 eligible file was not examined.",
        )

    def test_partial_requires_a_limit_hit(self):
        with pytest.raises(ValidationError, match="at least one limit hit"):
            self._report(
                RetrievalStatus.PARTIAL, [], "Retrieval is PARTIAL: stopped early."
            )

    def test_partial_summary_must_say_partial(self):
        with pytest.raises(ValidationError, match="must say the analysis is partial"):
            self._report(
                RetrievalStatus.PARTIAL,
                [self._hit()],
                "Retrieval stopped early.",
            )

    def test_complete_cannot_record_a_hit(self):
        with pytest.raises(ValidationError, match="COMPLETE retrieval"):
            self._report(
                RetrievalStatus.COMPLETE,
                [self._hit()],
                "Retrieval is COMPLETE: all files examined.",
            )

    def test_partial_report_carries_remaining_work(self):
        report = self._report(
            RetrievalStatus.PARTIAL,
            [self._hit()],
            "Retrieval is PARTIAL: 1 eligible file was not examined.",
        )
        assert report.limit_hits[0].remaining_work
        assert "not examined" in report.summary


class TestCollectorLimits:
    def test_complete_scan_explains_full_coverage(self, tmp_path):
        ws = _repo(tmp_path, MATCHING_FILES)

        outcome = _collect(ws, RetrievalLimits())

        assert outcome.report.status is RetrievalStatus.COMPLETE
        assert outcome.report.limit_hits == []
        assert outcome.report.files_examined == outcome.report.files_eligible
        assert outcome.report.search_results == len(MATCHING_FILES)
        assert outcome.report.bytes_read > 0
        assert "COMPLETE" in outcome.report.summary
        assert "No retrieval limit was reached" in outcome.report.summary
        assert outcome.records

    def test_max_files_reports_unexamined_remaining_work(self, tmp_path):
        ws = _repo(tmp_path, MATCHING_FILES)

        outcome = _collect(ws, RetrievalLimits(max_files=1))

        report = outcome.report
        assert report.status is RetrievalStatus.PARTIAL
        assert report.files_examined == 1
        assert report.files_eligible == len(MATCHING_FILES)
        hit = next(h for h in report.limit_hits if h.limit is RetrievalLimit.MAX_FILES)
        assert hit.allowed == 1
        assert hit.observed == len(MATCHING_FILES)
        assert "eligible file(s) were not examined" in hit.remaining_work
        assert "PARTIAL" in report.summary
        assert "not examined" in report.summary
        assert "does not cover the whole repository" in report.summary

    def test_bytes_per_file_reports_unread_tail(self, tmp_path):
        ws = _repo(
            tmp_path,
            {
                "README.md": "widget " + ("x" * 5000),
                "docs/guide.md": "widget option\n",
            },
        )

        outcome = _collect(
            ws,
            RetrievalLimits(max_bytes_per_file=100, max_total_bytes=1_000_000),
        )

        report = outcome.report
        assert report.status is RetrievalStatus.PARTIAL
        hit = next(
            h
            for h in report.limit_hits
            if h.limit is RetrievalLimit.MAX_BYTES_PER_FILE
        )
        assert hit.allowed == 100
        assert hit.observed > 100
        assert "trailing byte(s)" in hit.remaining_work
        assert "README.md" in hit.remaining_work
        # Per-file truncation does not stop the scan of other files.
        assert report.files_examined == report.files_eligible

    def test_total_bytes_stops_the_scan_with_remaining_work(self, tmp_path):
        ws = _repo(tmp_path, MATCHING_FILES)

        outcome = _collect(
            ws,
            RetrievalLimits(max_bytes_per_file=1000, max_total_bytes=5),
        )

        report = outcome.report
        assert report.status is RetrievalStatus.PARTIAL
        assert report.bytes_read == 5
        hit = next(
            h
            for h in report.limit_hits
            if h.limit is RetrievalLimit.MAX_TOTAL_BYTES
        )
        assert hit.allowed == 5
        assert hit.observed == 5
        assert "total retrieval budget was exhausted" in hit.remaining_work
        assert report.files_examined < report.files_eligible

    def test_search_results_cap_is_reported(self, tmp_path):
        ws = _repo(tmp_path, MATCHING_FILES)

        outcome = _collect(ws, RetrievalLimits(max_search_results=1))

        report = outcome.report
        assert report.status is RetrievalStatus.PARTIAL
        assert report.search_results == 1
        hit = next(
            h
            for h in report.limit_hits
            if h.limit is RetrievalLimit.MAX_SEARCH_RESULTS
        )
        assert hit.allowed == 1
        assert hit.observed == 2
        assert "was not retained" in hit.remaining_work

    def test_wall_clock_limit_is_reported(self, tmp_path):
        ws = _repo(tmp_path, MATCHING_FILES)

        outcome = _collect(ws, RetrievalLimits(max_seconds=1e-9))

        report = outcome.report
        assert report.status is RetrievalStatus.PARTIAL
        assert report.files_examined == 0
        hit = next(
            h for h in report.limit_hits if h.limit is RetrievalLimit.MAX_SECONDS
        )
        assert hit.allowed == pytest.approx(1e-9)
        assert "retrieval budget was exhausted" in hit.remaining_work
        assert "eligible file(s) were not examined" in hit.remaining_work
