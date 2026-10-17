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
    parse_git_authors,
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


def test_parse_git_authors_groups_by_email_local_part():
    """Group authors by lowercase email local part first and keep the longest name."""
    inline_git_log = """
Ben-Hur Ott|benhur@work.com
Ben-Hur Santos Ott|benhur@personal.org
Ben-Hur|benhur@corp.net
"""
    authors = parse_git_authors(inline_git_log)
    assert authors == ["Ben-Hur Santos Ott"]


def test_parse_git_authors_token_subset_drop_middle_tokens():
    """Drop middle tokens when one name is a token subset of another, keeping the longest."""
    inline_git_log = """
Ben-Hur Ott|ott1@domain.com
Ben-Hur Santos Ott|ott2@different-domain.com
"""
    authors = parse_git_authors(inline_git_log)
    assert authors == ["Ben-Hur Santos Ott"]


def test_parse_git_authors_collapses_spaces_and_lowercases():
    """Whitespace is collapsed and case normalized when matching names."""
    inline_git_log = """
Ben-Hur    Ott|first@a.com
ben-hur   santos   ott|second@b.com
"""
    authors = parse_git_authors(inline_git_log)
    assert len(authors) == 1
    # Keeps the longest representation
    assert authors[0].lower().replace(" ", "") == "ben-hursantosott"


def test_parse_git_authors_top_three_limit():
    """Return at most 3 distinct owners ranked by commit frequency."""
    inline_git_log = """
Alice Smith|asmith@work.com
Alice Smith|asmith@work.com
Alice Smith|asmith@work.com
Bob Jones|bjones@work.com
Bob Jones|bjones@work.com
Charlie Chaplin|cchaplin@work.com
David Bowie|dbowie@work.com
Eve Adams|eadams@work.com
"""
    authors = parse_git_authors(inline_git_log, n=3)
    assert len(authors) == 3
    assert authors == ["Alice Smith", "Bob Jones", "Charlie Chaplin"]


def test_parse_git_authors_distinct_persons_do_not_merge():
    """Authors with different first or last names do not merge."""
    inline_git_log = """
Alice Smith|asmith@domain.com
Bob Smith|bsmith@domain.com
Alice Jones|ajones@domain.com
"""
    authors = parse_git_authors(inline_git_log, n=3)
    assert len(authors) == 3
    assert set(authors) == {"Alice Smith", "Bob Smith", "Alice Jones"}


@patch("subprocess.run")
def test_from_git_authors_uses_format_an_ae(mock_subproc, tmp_path):
    """from_git_authors passes --format=%an|%ae and returns at most 3 distinct owners."""
    (tmp_path / ".git").mkdir()

    mock_proc = mock_subproc.return_value
    mock_proc.returncode = 0
    mock_proc.stdout = """
Ben-Hur Ott|benhur@work.com
Ben-Hur Santos Ott|benhur@personal.org
Alice Smith|alice@work.com
Alice Smith|alice@work.com
Charlie|charlie@work.com
David|david@work.com
"""

    authors = from_git_authors(tmp_path, "src/core.py")
    assert mock_subproc.called
    cmd_called = mock_subproc.call_args[0][0]
    assert "--format=%an|%ae" in cmd_called
    assert len(authors) == 3
    # Top 3: Alice Smith (2 commits), Ben-Hur Santos Ott (2 commits), Charlie (1 commit)
    assert "Ben-Hur Santos Ott" in authors
    assert "Alice Smith" in authors
    assert len(authors) <= 3

