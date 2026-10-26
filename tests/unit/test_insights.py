"""Orientation and test-guidance insights (PS04 background alignment)."""

from repomate_core.insights import build_orientation, build_test_guidance
from repomate_core.repository.inspect import inspect_repository


def _snapshot(local_workspace):
    return inspect_repository(
        local_workspace, owner="acme", name="fixture-project",
        url="https://github.com/acme/fixture-project",
    )


def test_orientation_maps_repo_for_newcomer(local_workspace):
    snapshot = _snapshot(local_workspace)
    from repomate_core.contracts import EvidenceRecord

    evidence = [
        EvidenceRecord(id="ev1", kind="DOC", path="docs/usage.md",
                       start_line=1, end_line=4, snippet="s", rationale="timeout docs"),
    ]
    orientation = build_orientation(local_workspace, snapshot, evidence)

    assert orientation.generated_by == "snapshot-v1"
    assert "fixture-project" in orientation.summary
    assert "MIT" in orientation.summary  # license surfaced for reuse decisions
    paths = {k.path: k.role for k in orientation.key_paths}
    assert "README.md" in paths and "overview" in paths["README.md"]
    assert "docs/usage.md" in paths and "relevant to this task" in paths["docs/usage.md"]
    assert "py" in orientation.languages


def test_test_guidance_names_relevant_tests_and_commands(local_workspace):
    snapshot = _snapshot(local_workspace)
    from repomate_core.contracts import EvidenceRecord

    evidence = [
        EvidenceRecord(id="ev1", kind="TEST", path="tests/test_core.py",
                       start_line=1, end_line=3, snippet="s",
                       rationale="matches keywords: timeout"),
    ]
    guidance = build_test_guidance(local_workspace, snapshot, evidence)

    assert guidance.run_command == "python -m pytest -q"
    assert guidance.focused_command == "python -m pytest -q tests/test_core.py"
    assert guidance.relevant_tests[0].path == "tests/test_core.py"
    assert "keyword-based" in guidance.note
    assert "full suite" in guidance.note
    # Guidance is built before verification; it must not claim execution.
    assert "already executed" not in guidance.note
    assert "receipt" in guidance.note


def test_test_guidance_honest_without_toolchain(tmp_path):
    from tests.unit.test_inspect import _git  # reuse helper

    repo = tmp_path / "bare"
    repo.mkdir()
    (repo / "readme.md").write_text("# bare\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")

    from repomate_core.repository.workspace import RepoWorkspace

    ws = RepoWorkspace.from_local(repo)
    snapshot = inspect_repository(ws, owner="a", name="b", url="u")
    guidance = build_test_guidance(ws, snapshot, [])
    assert guidance.run_command is None
    assert "No supported test command" in guidance.note


def test_path_token_matching_surfaces_named_files(tmp_path, local_workspace):
    """Agentic-RAG-lite: an issue naming a module must surface that file
    even when file content never uses the word."""
    import json

    from repomate_core.evidence.collector import collect_evidence

    records = collect_evidence(
        local_workspace, _snapshot(local_workspace), "fix the widgetloader crash"
    )
    assert records, "expected at least one evidence record"
