"""Deterministic repository orientation for newcomers.

Built entirely from the pinned snapshot and collected evidence — no model
call, no invented facts. Each key path carries the reason it was chosen
(evidence citation or structural role), so a newcomer can trace every
claim in the map.
"""

from __future__ import annotations

import re

from repomate_core.contracts import (
    EvidenceRecord,
    KeyPath,
    Orientation,
    RepositorySnapshot,
)
from repomate_core.repository.workspace import RepoWorkspace

_ROLES = (
    ("readme_path", "project overview and quickstart"),
    ("contributing_path", "contributor instructions"),
)


def build_orientation(
    ws: RepoWorkspace,
    snapshot: RepositorySnapshot,
    evidence: list[EvidenceRecord],
) -> Orientation:
    key_paths: list[KeyPath] = []
    for attr, role in _ROLES:
        path = getattr(snapshot, attr, None)
        if path:
            key_paths.append(KeyPath(path=path, role=role))

    for record in evidence[:6]:
        if record.kind.value in ("SOURCE", "DOC") and record.path not in {
            k.path for k in key_paths
        }:
            key_paths.append(
                KeyPath(
                    path=record.path,
                    role=f"relevant to this task ({record.rationale[:80]})",
                )
            )

    return Orientation(
        summary=_summarize(ws, snapshot, evidence),
        key_paths=key_paths[:8],
        languages=dict(list(snapshot.languages.items())[:5]),
        entry_points=[
            KeyPath(path=e.path, role=f"{e.kind}: {e.detail}"[:100])
            for e in snapshot.entry_points[:5]
        ],
        generated_by="snapshot-v1",
    )


def _summarize(
    ws: RepoWorkspace, snapshot: RepositorySnapshot, evidence: list[EvidenceRecord]
) -> str:
    primary = max(snapshot.languages, key=snapshot.languages.get) if snapshot.languages else "unknown"
    parts = [
        f"{snapshot.owner}/{snapshot.name} is a {primary}-dominant repository "
        f"({snapshot.file_count} tracked files, default branch {snapshot.default_branch})."
    ]
    readme_line = _readme_first_line(ws, snapshot)
    if readme_line:
        parts.append(f'The README opens with: "{readme_line}"')
    lic = snapshot.license
    if lic.spdx_id:
        parts.append(f"License: {lic.spdx_id} ({lic.status.value.lower()}).")
    else:
        parts.append(f"License status: {lic.status.value.lower()} — {lic.note}")
    if evidence:
        parts.append(
            f"{len(evidence)} evidence location(s) connect this task to the codebase."
        )
    return " ".join(parts)


def _readme_first_line(ws: RepoWorkspace, snapshot: RepositorySnapshot) -> str:
    if not snapshot.readme_path:
        return ""
    try:
        text = ws.read_text(snapshot.readme_path, max_chars=4000)
    except Exception:
        return ""
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("!", "[")):
            return re.sub(r"\s+", " ", line)[:160]
    return ""
