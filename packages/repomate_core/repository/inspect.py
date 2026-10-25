"""Repository inspection: build the pinned :class:`RepositorySnapshot`."""

from __future__ import annotations

import json
from pathlib import Path

from repomate_core.contracts import (
    EntryPoint,
    LicenseInfo,
    LicenseStatus,
    RepositorySnapshot,
)
from repomate_core.repository.workspace import RepoWorkspace

_LICENSE_FILENAMES = (
    "LICENSE", "LICENCE", "COPYING", "NOTICE",
    "LICENSE.md", "LICENSE.txt", "LICENCE.md", "COPYING.txt",
)

# Content sniffs for the handful of licenses that dominate public code.
_LICENSE_SNIFFS = (
    ("Apache License", "Apache-2.0"),
    ("Mozilla Public License", "MPL-2.0"),
    ("GNU GENERAL PUBLIC LICENSE", "GPL-2.0-or-later"),
    ("GNU LESSER GENERAL PUBLIC LICENSE", "LGPL-2.1-or-later"),
    ("GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL-3.0-or-later"),
    ("Permission is hereby granted, free of charge", "MIT"),
    ("Redistribution and use in source and binary forms", "BSD-3-Clause"),
    ("Boost Software License", "BSL-1.0"),
    ("The Unlicense", "Unlicense"),
    ("CC0 1.0 Universal", "CC0-1.0"),
)

_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala",
    ".sh", ".m", ".mm", ".lua", ".pl", ".r", ".jl",
}


def inspect_repository(
    ws: RepoWorkspace, *, owner: str, name: str, url: str
) -> RepositorySnapshot:
    files = ws.ls_files()
    return RepositorySnapshot(
        owner=owner,
        name=name,
        url=url,
        default_branch=ws.default_branch,
        commit_sha=ws.commit_sha,
        license=detect_license(ws, files),
        languages=language_census(files),
        file_count=len(files),
        readme_path=_find_first(files, ("README.md", "README.rst", "README.txt", "README")),
        contributing_path=_find_first(
            files, ("CONTRIBUTING.md", "CONTRIBUTING.rst", "CONTRIBUTING", ".github/CONTRIBUTING.md")
        ),
        entry_points=find_entry_points(ws, files),
    )


def detect_license(ws: RepoWorkspace, files: list[str]) -> LicenseInfo:
    for candidate in _LICENSE_FILENAMES:
        if candidate in files:
            text = ws.read_text(candidate, max_chars=40_000)
            for needle, spdx in _LICENSE_SNIFFS:
                if needle.lower() in text.lower():
                    return LicenseInfo(
                        status=LicenseStatus.RECOGNIZED,
                        spdx_id=spdx,
                        file_path=candidate,
                        note=f"recognized as {spdx} from license file content",
                    )
            return LicenseInfo(
                status=LicenseStatus.UNKNOWN,
                file_path=candidate,
                note="license file present but not recognized; review manually",
            )
    return LicenseInfo(
        status=LicenseStatus.ABSENT,
        note="no license file found; the repository may not permit reuse",
    )


def language_census(files: list[str], top: int = 8) -> dict[str, float]:
    counts: dict[str, int] = {}
    total = 0
    for f in files:
        ext = Path(f).suffix.lower()
        if ext in _CODE_EXTENSIONS:
            counts[ext] = counts.get(ext, 0) + 1
            total += 1
    if not total:
        return {}
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return {ext.lstrip("."): round(n / total * 100, 1) for ext, n in ranked}


def find_entry_points(ws: RepoWorkspace, files: list[str]) -> list[EntryPoint]:
    entries: list[EntryPoint] = []

    if "package.json" in files:
        try:
            pkg = json.loads(ws.read_text("package.json", max_chars=100_000))
        except (ValueError, OSError):
            pkg = {}
        main = pkg.get("main")
        if main:
            entries.append(EntryPoint(path=main, kind="manifest", detail="package.json main"))
        for name in (pkg.get("bin") or {}):
            entries.append(EntryPoint(path=str(name), kind="script", detail="package.json bin"))
        if not main and not pkg.get("bin"):
            entries.append(EntryPoint(path="package.json", kind="manifest", detail="no main/bin declared"))

    if "pyproject.toml" in files:
        detail = "pyproject.toml"
        scripts = _toml_project_scripts(ws)
        if scripts:
            detail = f"pyproject.toml scripts: {', '.join(scripts[:5])}"
        entries.append(EntryPoint(path="pyproject.toml", kind="manifest", detail=detail))

    if "Makefile" in files:
        entries.append(EntryPoint(path="Makefile", kind="makefile", detail="build/test targets"))
    if "go.mod" in files:
        entries.append(EntryPoint(path="go.mod", kind="manifest", detail="Go module"))
    return entries


def _toml_project_scripts(ws: RepoWorkspace) -> list[str]:
    try:
        import tomllib  # Python 3.11+; pyproject scripts are skipped on 3.10
    except ImportError:
        return []
    try:
        data = tomllib.loads(ws.read_text("pyproject.toml", max_chars=100_000))
    except (ValueError, OSError):
        return []
    scripts = (data.get("project") or {}).get("scripts") or {}
    return [str(k) for k in scripts]


def _find_first(files: list[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in files:
            return candidate
    return None
