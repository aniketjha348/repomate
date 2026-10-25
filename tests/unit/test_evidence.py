"""Unit tests for evidence collection against the local fixture repo."""


def test_collects_issue_and_doc_evidence(local_workspace):
    from repomate_core.contracts import GitHubIssue, LicenseInfo, LicenseStatus
    from repomate_core.evidence.collector import collect_evidence
    from repomate_core.repository.inspect import inspect_repository

    snapshot = inspect_repository(
        local_workspace, owner="acme", name="fixture-project",
        url="https://github.com/acme/fixture-project",
    )
    assert snapshot.license.status is LicenseStatus.RECOGNIZED
    assert snapshot.license.spdx_id == "MIT"
    assert snapshot.readme_path == "README.md"

    issue = GitHubIssue(url="u", number=7, title="Timeout option not documented", body="Please document FIXTURE_TIMEOUT.")
    records = collect_evidence(
        local_workspace, snapshot,
        "Add documentation for the timeout option to the README",
        issue,
    )

    kinds = [r.kind.value for r in records]
    assert kinds[0] == "ISSUE"
    assert "DOC" in kinds
    readme = next(r for r in records if r.path == "README.md")
    assert readme.start_line is not None and readme.end_line is not None
    assert "timeout" in readme.snippet.lower()
    assert readme.rationale


def test_no_match_returns_only_issue(local_workspace):
    from repomate_core.contracts import GitHubIssue
    from repomate_core.evidence.collector import collect_evidence
    from repomate_core.repository.inspect import inspect_repository

    snapshot = inspect_repository(
        local_workspace, owner="acme", name="fixture-project",
        url="https://github.com/acme/fixture-project",
    )
    issue = GitHubIssue(url="u", number=8, title="zzz qqq vvv", body="")
    records = collect_evidence(local_workspace, snapshot, "zzz qqq vvv", issue)
    assert [r.kind.value for r in records] == ["ISSUE"]
