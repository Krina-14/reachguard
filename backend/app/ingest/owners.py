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
from collections import defaultdict
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


def _normalize_name_tokens(name: str) -> list[str]:
    """Lowercase and collapse whitespace into tokens."""
    return [token for token in name.strip().lower().split() if token]


def _names_match(tokens1: list[str], tokens2: list[str]) -> bool:
    """Check if two tokenized names match directly or via middle token dropping."""
    if not tokens1 or not tokens2:
        return False
    if tokens1 == tokens2:
        return True
    if len(tokens1) >= 2 and len(tokens2) >= 2:
        if tokens1[0] == tokens2[0] and tokens1[-1] == tokens2[-1]:
            s1, s2 = set(tokens1), set(tokens2)
            if s1.issubset(s2) or s2.issubset(s1):
                return True
    return False


def _extract_local_part(email: str) -> str | None:
    """Extract lowercase email local part before the @ character."""
    if not email:
        return None
    cleaned = email.strip("<> \"'\t")
    if "@" in cleaned:
        local = cleaned.split("@")[0].strip().lower()
        return local if local else None
    return None


class _AuthorEntry:
    def __init__(self, raw_name: str, raw_email: str, first_seen: int):
        self.raw_name = raw_name
        self.raw_email = raw_email
        self.first_seen = first_seen
        self.count = 0
        self.local_part = _extract_local_part(raw_email)
        self.tokens = _normalize_name_tokens(raw_name)


def parse_git_authors(output: str, n: int = 3) -> list[str]:
    """
    Parse git log output (--format=%an|%ae), group authors, and return at most 3 distinct owners.

    Grouping order:
    1. Group by lowercase email local part first.
    2. Then group by normalized name (lowercase, collapse spaces, drop middle tokens when one name
       is a token subset of another, keeping the longest representation).
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return []

    entries: dict[tuple[str, str], _AuthorEntry] = {}
    entry_list: list[_AuthorEntry] = []

    for idx, line in enumerate(lines):
        if "|" in line:
            raw_name, _, raw_email = line.partition("|")
        else:
            raw_name, raw_email = line, ""
        raw_name = raw_name.strip("<> \"'\t")
        raw_email = raw_email.strip("<> \"'\t")

        if not raw_name and not raw_email:
            continue
        if not raw_name:
            raw_name = raw_email.split("@")[0].strip()

        key = (raw_name, raw_email)
        if key not in entries:
            entry = _AuthorEntry(raw_name, raw_email, first_seen=idx)
            entries[key] = entry
            entry_list.append(entry)
        entries[key].count += 1

    if not entry_list:
        return []

    m = len(entry_list)
    parent = list(range(m))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    # Phase 1: Group by lowercase email local part first
    email_groups: dict[str, list[int]] = defaultdict(list)
    for i, entry in enumerate(entry_list):
        if entry.local_part:
            email_groups[entry.local_part].append(i)

    for idxs in email_groups.values():
        for j in idxs[1:]:
            union(idxs[0], j)

    # Phase 2: Then by normalized name
    for i in range(m):
        for j in range(i + 1, m):
            if find(i) != find(j):
                if _names_match(entry_list[i].tokens, entry_list[j].tokens):
                    union(i, j)

    clusters: dict[int, list[_AuthorEntry]] = defaultdict(list)
    for i in range(m):
        clusters[find(i)].append(entry_list[i])

    ranked_clusters = []
    for members in clusters.values():
        total_commits = sum(e.count for e in members)
        min_first_seen = min(e.first_seen for e in members)

        # Keep the longest name representation
        best_entry = max(
            members,
            key=lambda e: (
                len(e.raw_name),
                e.count,
                sum(1 for c in e.raw_name if c.isupper()),
            ),
        )
        canonical_name = best_entry.raw_name
        ranked_clusters.append((total_commits, min_first_seen, canonical_name))

    ranked_clusters.sort(key=lambda x: (-x[0], x[1]))
    limit = min(n, 3) if n > 0 else 3
    return [item[2] for item in ranked_clusters[:limit]]


def deduplicate_owners(names: list[str], max_owners: int = 3) -> list[str]:
    """
    Deduplicate and merge owner names using token subset matching (dropping middle tokens),
    keeping the longest name representation, and returning at most max_owners (default 3).
    """
    cleaned = [n.strip() for n in names if n and n.strip()]
    if not cleaned:
        return []

    unique_names: list[str] = []
    seen = set()
    for name in cleaned:
        if name not in seen:
            seen.add(name)
            unique_names.append(name)

    m = len(unique_names)
    if m <= 1:
        return unique_names[:max_owners]

    tokens_list = [_normalize_name_tokens(name) for name in unique_names]
    parent = list(range(m))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(m):
        for j in range(i + 1, m):
            if find(i) != find(j):
                if _names_match(tokens_list[i], tokens_list[j]):
                    union(i, j)

    clusters: dict[int, list[str]] = defaultdict(list)
    for i in range(m):
        clusters[find(i)].append(unique_names[i])

    result: list[str] = []
    for members in clusters.values():
        best_name = max(
            members,
            key=lambda name: (
                len(name),
                sum(1 for c in name if c.isupper()),
            ),
        )
        result.append(best_name)

    return result[:max_owners]



def from_git_authors(root: str | Path, file: str, n: int = 3) -> list[str]:
    """
    Extract at most 3 git commit authors for a file using `git log --format=%an|%ae`.

    Skips execution if the repository root has no .git directory.
    """
    root_path = Path(root).resolve()
    git_dir = root_path / ".git"
    if not git_dir.exists():
        return []

    norm_file = file.replace("\\", "/").lstrip("/")

    cmd = ["git", "log", "-n", "100", "--format=%an|%ae", "--", norm_file]

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

        return parse_git_authors(proc.stdout, n=n)

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
