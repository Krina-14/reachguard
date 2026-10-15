"""
ReachGuard — Module Ownership Resolution.

Resolves owners for repository modules:
1. CODEOWNERS file parsing (from root, .github/, or docs/) with fnmatch pattern matching.
2. Git author analysis via `git log --format=%an` (for git repos only; skipped for zip uploads).
3. Produces Owner records with kind 'codeowners' or 'author'.
"""

from __future__ import annotations

import fnmatch
import logging
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def from_codeowners(root: str | Path) -> Callable[[str], list[str]]:
    """
    Parse CODEOWNERS from root, .github/, or docs/.

    Returns a matcher function `get_owners(rel_file_path) -> list[str]`
    where the last matching rule wins.
    """
    root_path = Path(root).resolve()
    candidate_paths = [
        root_path / "CODEOWNERS",
        root_path / ".github" / "CODEOWNERS",
        root_path / "docs" / "CODEOWNERS",
    ]

    rules: list[tuple[str, list[str]]] = []

    for path in candidate_paths:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = line.split()
                    pattern = parts[0]
                    owners = parts[1:]
                    rules.append((pattern, owners))
                break  # Stop at first valid CODEOWNERS file
            except OSError as exc:
                logger.warning("Could not read CODEOWNERS at %s: %s", path, exc)

    def matcher(rel_file: str) -> list[str]:
        # Normalize relative file path
        norm_file = rel_file.replace("\\", "/").lstrip("/")
        matching_owners: list[str] = []

        for pattern, owners in rules:
            p = pattern.strip()

            # Directory pattern (e.g. "app/" or "/app/")
            if p.endswith("/"):
                clean_p = p.lstrip("/").rstrip("/")
                if norm_file.startswith(clean_p + "/") or norm_file == clean_p:
                    matching_owners = owners
                continue

            # Root-anchored pattern (e.g. "/setup.py" or "/app/*.py")
            if p.startswith("/"):
                clean_p = p.lstrip("/")
                if fnmatch.fnmatch(norm_file, clean_p):
                    matching_owners = owners
                continue

            # Anywhere pattern (e.g. "*.py" or "docs/*")
            if fnmatch.fnmatch(norm_file, p) or fnmatch.fnmatch(norm_file, f"*/{p}"):
                matching_owners = owners

        return matching_owners

    return matcher


def from_git_authors(root: str | Path, file: str, n: int = 3) -> list[str]:
    """
    Extract the top n git commit authors for a file using `git log`.

    Skips execution if the repository root has no .git directory.
    """
    root_path = Path(root).resolve()
    git_dir = root_path / ".git"
    if not git_dir.exists():
        return []

    norm_file = file.replace("\\", "/").lstrip("/")

    cmd = ["git", "log", "-n", "100", "--format=%an", "--", norm_file]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root_path),
            timeout=10,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return []

        authors = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not authors:
            return []

        counts = Counter(authors)
        return [author for author, _ in counts.most_common(n)]

    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git log failed or timed out for %s: %s", norm_file, exc)
        return []


def resolve_module_owners(
    root: str | Path,
    rel_file: str,
    is_git: bool,
    codeowners_fn: Callable[[str], list[str]],
    top_authors_count: int = 3,
) -> list[dict[str, str]]:
    """
    Determine owners for a module file.

    Returns a list of dicts: `[{"name": ..., "kind": "codeowners" | "author"}, ...]`.
    If neither CODEOWNERS nor git authors match, returns empty list (UI shows 'unassigned').
    """
    # 1. Check CODEOWNERS first
    co_owners = codeowners_fn(rel_file)
    if co_owners:
        return [{"name": owner, "kind": "codeowners"} for owner in co_owners]

    # 2. Check git authors if git repo
    if is_git:
        authors = from_git_authors(root, rel_file, n=top_authors_count)
        if authors:
            return [{"name": author, "kind": "author"} for author in authors]

    return []
