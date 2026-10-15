"""
Unit tests for backend/app/ingest/owners.py.

Covers:
- CODEOWNERS parsing from root, .github/, and docs/
- Pattern matching with fnmatch (directory, extension, root-anchored)
- Last matching rule wins in CODEOWNERS
- Git author resolution via subprocess
- Fallback to unassigned when neither applies
"""

from unittest.mock import patch

from app.ingest.owners import (
    from_codeowners,
    from_git_authors,
    resolve_module_owners,
)


def test_from_codeowners_parsing_and_last_rule_wins(tmp_path):
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("""
# Global owners
* @global-team

# Backend team owns app/
app/ @backend-team

# Security owns auth specifically
app/auth/* @security-team @lead-dev

# Setup file has single owner
/setup.py @infra-lead
""")

    matcher = from_codeowners(tmp_path)

    # Global pattern matches root files
    assert matcher("README.md") == ["@global-team"]

    # app/ directory rule
    assert matcher("app/main.py") == ["@backend-team"]

    # Last matching rule wins: app/auth/security.py matches app/ and app/auth/* -> @security-team, @lead-dev
    assert matcher("app/auth/security.py") == ["@security-team", "@lead-dev"]

    # Root anchored pattern
    assert matcher("setup.py") == ["@infra-lead"]
    assert matcher("sub/setup.py") == ["@global-team"]


def test_from_codeowners_not_found(tmp_path):
    matcher = from_codeowners(tmp_path)
    assert matcher("app/main.py") == []


def test_from_git_authors_skipped_when_no_git(tmp_path):
    # Zip upload has no .git directory
    authors = from_git_authors(tmp_path, "main.py")
    assert authors == []


@patch("subprocess.run")
def test_from_git_authors_top_n(mock_subproc, tmp_path):
    # Simulate .git directory
    (tmp_path / ".git").mkdir()

    mock_proc = mock_subproc.return_value
    mock_proc.returncode = 0
    mock_proc.stdout = "Alice\nBob\nAlice\nAlice\nCharlie\nBob\n"

    authors = from_git_authors(tmp_path, "app/main.py", n=2)
    # Alice has 3 commits, Bob has 2, Charlie has 1 -> top 2 are Alice, Bob
    assert authors == ["Alice", "Bob"]


def test_resolve_module_owners_priority(tmp_path):
    # 1. CODEOWNERS match takes precedence over git authors
    def mock_codeowners(file: str) -> list[str]:
        if "main.py" in file:
            return ["@core-team"]
        return []

    res1 = resolve_module_owners(
        root=tmp_path,
        rel_file="app/main.py",
        is_git=True,
        codeowners_fn=mock_codeowners,
    )
    assert res1 == [{"name": "@core-team", "kind": "codeowners"}]

    # 2. When CODEOWNERS has no match, falls back to git authors if is_git
    with patch("app.ingest.owners.from_git_authors", return_value=["Alice", "Bob"]):
        res2 = resolve_module_owners(
            root=tmp_path,
            rel_file="app/other.py",
            is_git=True,
            codeowners_fn=mock_codeowners,
        )
        assert res2 == [
            {"name": "Alice", "kind": "author"},
            {"name": "Bob", "kind": "author"},
        ]

    # 3. Zip upload with no match returns empty list (unassigned)
    res3 = resolve_module_owners(
        root=tmp_path,
        rel_file="app/other.py",
        is_git=False,
        codeowners_fn=mock_codeowners,
    )
    assert res3 == []
