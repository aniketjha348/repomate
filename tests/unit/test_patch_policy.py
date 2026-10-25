"""Unit tests for unified-diff parsing and the docs patch policy."""

import pytest

from repomate_core.artifacts.patch import (
    DOCS_PATCH_POLICY,
    PatchPolicyError,
    extract_affected_paths,
    validate_patch,
)

SAMPLE_DIFF = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,2 +1,5 @@
 # Title
+
+## New Section
"""


def _diff_for(*paths: str) -> str:
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-x\n+y\n"
        for p in paths
    )


class TestExtractPaths:
    def test_extracts_paths(self):
        assert extract_affected_paths(SAMPLE_DIFF) == ["README.md"]

    def test_rejects_traversal(self):
        with pytest.raises(PatchPolicyError):
            extract_affected_paths(_diff_for("../../etc/passwd"))

    def test_rejects_absolute(self):
        with pytest.raises(PatchPolicyError):
            extract_affected_paths("+++ b//etc/passwd\n")

    def test_deduplicates(self):
        paths = extract_affected_paths(_diff_for("docs/a.md", "docs/a.md"))
        assert paths == ["docs/a.md"]


class TestDocsPolicy:
    @pytest.mark.parametrize(
        "path", ["README.md", "README.rst", "docs/guide.md", "doc/foo.txt", "NOTES.md"]
    )
    def test_allowed(self, path):
        assert validate_patch(_diff_for(path), DOCS_PATCH_POLICY) == []

    @pytest.mark.parametrize(
        "path",
        [
            "src/fixture/core.py",            # source outside docs scope
            "package.json",
            ".github/workflows/ci.yml",       # CI is always forbidden
            "docs/../src/core.py",            # traversal into source
            "secrets/token.key",
            ".env.local",
        ],
    )
    def test_denied(self, path):
        violations = validate_patch(_diff_for(path), DOCS_PATCH_POLICY)
        assert violations, f"expected {path} to be rejected"

    def test_empty_patch_flagged(self):
        assert validate_patch("no diff headers here", DOCS_PATCH_POLICY)

    def test_oversized_patch_flagged(self):
        big = _diff_for("README.md") * 1200
        violations = validate_patch(big, DOCS_PATCH_POLICY)
        assert any("exceeds" in v for v in violations)
