"""Git workspace management for a pinned repository snapshot.

A :class:`RepoWorkspace` wraps a git checkout (a shallow clone in
production, a local fixture in tests). It guarantees: the run is pinned to
the cloned commit, file access is path-traversal-safe, diffs are produced
with CRLF translation disabled so patches apply on any platform, and git
never prompts for credentials. Subprocess mechanics live in
:mod:`repomate_core.repository.git_runner`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from repomate_core.repository.errors import WorkspaceError
from repomate_core.repository.git_runner import run_git
from repomate_core.safety.url_guard import GitHubRef

CLONE_TIMEOUT_SECONDS = 300


class RepoWorkspace:
    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).resolve()
        if not (self.root / ".git").exists():
            raise WorkspaceError(f"{self.root} is not a git repository")

    # -- construction ------------------------------------------------------

    @classmethod
    def from_github(
        cls,
        ref: GitHubRef,
        dest: Union[str, Path],
        *,
        token: Optional[str] = None,
        timeout: int = CLONE_TIMEOUT_SECONDS,
    ) -> "RepoWorkspace":
        # Absolute from the start: a relative dest combined with cwd=dest.parent
        # would make git clone into a nested path instead of dest itself.
        dest = Path(dest).absolute()
        if dest.exists():
            raise WorkspaceError(f"destination already exists: {dest}")
        # The store may only persist metadata (SQL mode), so the run's
        # parent directory is not guaranteed to exist yet.
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{ref.owner}/{ref.repo}.git"
        # Token, if present, travels via a git config extraHeader so it never
        # appears in argv-derived error messages.
        extra: list[str] = []
        if token:
            extra = ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: bearer {token}"]
        result = run_git(
            *extra, "clone", "--depth", "1", url, str(dest),
            timeout=timeout,
            cwd=dest.parent,
            check=False,
            redact=token,
        )
        if result.returncode != 0:
            raise WorkspaceError(
                f"git clone failed for {ref.owner}/{ref.repo} "
                f"(exit {result.returncode}); the repository must be public and reachable"
            )
        return cls(dest)

    @classmethod
    def from_local(cls, path: Union[str, Path]) -> "RepoWorkspace":
        return cls(path)

    def clone_to(
        self,
        dest: Union[str, Path],
        *,
        timeout: int = CLONE_TIMEOUT_SECONDS,
    ) -> "RepoWorkspace":
        """Create an independent checkout pinned to this workspace's HEAD.

        Verification uses this to run the baseline and patched checks in
        separate, equivalent workspaces. ``--no-hardlinks`` copies the object
        store rather than sharing files, so one working tree cannot mutate the
        other's git data. The clone is verified to be at the same commit and
        any clone-side leftovers are cleaned before it is returned.
        """
        expected = self.commit_sha
        dest = Path(dest).absolute()
        if dest.exists():
            raise WorkspaceError(f"destination already exists: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = run_git(
            "clone",
            "--no-hardlinks",
            "--quiet",
            str(self.root),
            str(dest),
            timeout=timeout,
            cwd=dest.parent,
            check=False,
        )
        if result.returncode != 0:
            raise WorkspaceError(
                f"git clone of {self.root} failed (exit {result.returncode})"
            )
        clone = type(self)(dest)
        actual = clone.commit_sha
        if actual != expected:
            raise WorkspaceError(
                f"cloned workspace is at {actual}, expected the pinned commit {expected}"
            )
        clone.reset_hard()
        return clone

    # -- git plumbing --------------------------------------------------------

    @property
    def commit_sha(self) -> str:
        return run_git("rev-parse", "HEAD", cwd=self.root).stdout.strip()

    @property
    def default_branch(self) -> str:
        name = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.root).stdout.strip()
        return name if name and name != "HEAD" else "unknown"

    def git(self, *args: str, timeout: int = 120, check: bool = True,
            input_text: Optional[str] = None):
        return run_git(*args, cwd=self.root, timeout=timeout, check=check, input_text=input_text)

    # -- file access -----------------------------------------------------------

    def _resolve(self, rel_path: str) -> Path:
        candidate = (self.root / rel_path).resolve()
        if self.root != candidate and self.root not in candidate.parents:
            raise WorkspaceError(f"path escapes the workspace: {rel_path!r}")
        return candidate

    def ls_files(self) -> list[str]:
        out = run_git("ls-files", cwd=self.root).stdout
        return [line for line in out.splitlines() if line.strip()]

    def read_text(
        self, rel_path: str, *, max_chars: Optional[int] = 300_000
    ) -> str:
        target = self._resolve(rel_path)
        if not target.is_file():
            raise WorkspaceError(f"file not found in workspace: {rel_path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        return text if max_chars is None else text[:max_chars]

    def read_text_bounded(
        self, rel_path: str, *, max_bytes: int
    ) -> tuple[str, int, bool]:
        """Read at most ``max_bytes`` from a repository file.

        Returns ``(text, file_size, truncated)``. The file size is the actual
        on-disk size, so callers can report exactly how much was left unread
        without loading the remainder into memory.
        """
        target = self._resolve(rel_path)
        if not target.is_file():
            raise WorkspaceError(f"file not found in workspace: {rel_path}")
        size = target.stat().st_size
        with target.open("rb") as handle:
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace"), size, size > max_bytes

    def exists(self, rel_path: str) -> bool:
        return self._resolve(rel_path).exists()

    def write_text(self, rel_path: str, content: str) -> None:
        # The working tree is for repository files only; never let a model
        # edit git internals (config, hooks) through a proposed change.
        if ".git" in Path(rel_path.replace("\\", "/")).parts:
            raise WorkspaceError(f"refusing to write inside .git: {rel_path!r}")
        target = self._resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    # -- diff / patch -----------------------------------------------------------

    def diff(self) -> str:
        return run_git("diff", "--no-color", cwd=self.root).stdout

    def stage_intent_to_add(self, rel_path: str) -> None:
        run_git("add", "--intent-to-add", "--", rel_path, cwd=self.root)

    def apply_check(self, patch: str) -> tuple[bool, int, str]:
        """Run ``git apply --check``; returns (ok, exit_code, stderr)."""
        result = run_git("apply", "--check", "-", cwd=self.root, check=False, input_text=patch)
        return result.returncode == 0, result.returncode, result.stderr.strip()

    def apply(self, patch: str) -> None:
        """Apply a patch to the working tree (assumes it was checked)."""
        run_git("apply", "-", cwd=self.root, input_text=patch)

    def reset_hard(self) -> None:
        run_git("reset", "--hard", "HEAD", cwd=self.root)
        # Remove untracked leftovers so the snapshot is truly clean.
        run_git("clean", "-fdq", cwd=self.root)
