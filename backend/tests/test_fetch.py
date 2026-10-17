"""
Unit tests for backend/app/ingest/fetch.py.

Covers:
- URL validation (accept good, reject invalid hosts, schemes, injections, credentials)
- Zip extraction (normal zip extracts, zip-slip rejected, symlinks rejected, size/entry limits)
- iter_python_files (skips virtualenvs and vendor dirs, enforces MAX_PY_FILES)
- find_dependency_files (priority order: poetry.lock, requirements*.txt, Pipfile.lock)
- clone_repo (git command arguments, environment, timeout, and folder size limits)
"""

import io
import stat
import subprocess
import zipfile
from unittest.mock import patch

import pytest
from app.ingest.fetch import (
    GitCloneError,
    GitCloneTimeoutError,
    GitUrlValidationError,
    MaxPythonFilesExceededError,
    RepoSizeExceededError,
    ZipValidationError,
    clone_repo,
    extract_zip,
    find_dependency_files,
    iter_python_files,
    validate_git_url,
)
from fastapi import HTTPException

# ═════════════════════════════════════════════════════════════════════
# 1. URL Validation Tests
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "url, expected_owner, expected_repo",
    [
        ("https://github.com/octocat/Hello-World", "octocat", "Hello-World"),
        ("https://github.com/octocat/Hello-World.git", "octocat", "Hello-World"),
        ("https://github.com/octocat/Hello-World/", "octocat", "Hello-World"),
        ("https://github.com/octocat/Hello-World.git/", "octocat", "Hello-World"),
        ("https://github.com/Krina-14/reachguard", "Krina-14", "reachguard"),
        ("https://github.com/org_name.1/repo-name_2.3", "org_name.1", "repo-name_2.3"),
    ],
)
def test_validate_git_url_accepts_good(url, expected_owner, expected_repo):
    owner, repo = validate_git_url(url)
    assert owner == expected_owner
    assert repo == expected_repo


@pytest.mark.parametrize(
    "url",
    [
        "http://",
        "git@github.com:a/b",
        "https://github.com/a/b; rm -rf /",
        "https://evil.com/a/b",
        "file:///etc/passwd",
        "https://169.254.169.254/",
        "https://github.com/a",
        "https://github.com/a/b/c",
        "https://github.com/a/b?branch=main",
        "https://github.com/a/b#readme",
        "https://user:pass@github.com/a/b",
        "ftp://github.com/a/b",
        "javascript:alert(1)",
        "",
    ],
)
def test_validate_git_url_rejects_invalid(url):
    with pytest.raises(GitUrlValidationError) as exc_info:
        validate_git_url(url)

    # Must be HTTP 422
    assert exc_info.value.status_code == 422
    # Must be a ValueError subclass
    assert isinstance(exc_info.value, ValueError)
    assert isinstance(exc_info.value, HTTPException)


def test_validate_git_url_rejects_non_string():
    with pytest.raises(GitUrlValidationError) as exc_info:
        validate_git_url(None)  # type: ignore
    assert exc_info.value.status_code == 422


# ═════════════════════════════════════════════════════════════════════
# 2. Zip Extraction Tests (Normal, Zip-Slip, Symlinks, Limits)
# ═════════════════════════════════════════════════════════════════════


def test_extract_zip_normal(tmp_path):
    """A well-formed zip archive should extract cleanly."""
    zip_path = tmp_path / "valid.zip"
    dest_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("hello.txt", "Hello World")
        zf.writestr("sub/nested.py", "print('nested')")

    result = extract_zip(zip_path, dest_dir)
    assert result == dest_dir.resolve()
    assert (dest_dir / "hello.txt").read_text() == "Hello World"
    assert (dest_dir / "sub" / "nested.py").read_text() == "print('nested')"


@pytest.mark.parametrize(
    "malicious_filename",
    [
        "../evil.txt",
        "../../etc/passwd",
        "/tmp/evil.txt",
        "/evil.txt",
        "nested/../../evil.txt",
    ],
)
def test_extract_zip_rejects_zip_slip(tmp_path, malicious_filename):
    """Archives containing members that traverse outside dest_dir must be rejected."""
    zip_path = tmp_path / "zipslip.zip"
    dest_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(malicious_filename, "evil payload")
        zf.writestr("safe.txt", "safe file")

    with pytest.raises(ZipValidationError) as exc_info:
        extract_zip(zip_path, dest_dir)

    assert "Zip-slip detected" in exc_info.value.detail
    # Ensure no files leaked outside dest_dir
    assert not (tmp_path / "evil.txt").exists()


def test_extract_zip_rejects_symlinks(tmp_path):
    """Zip archives containing symlinks must be rejected."""
    zip_path = tmp_path / "symlink.zip"
    dest_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("regular.txt", "normal file")
        # Create a symlink entry in zip
        info = zipfile.ZipInfo("link_to_passwd")
        # Set POSIX file attributes to symlink (stat.S_IFLNK | 0o777)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")

    with pytest.raises(ZipValidationError) as exc_info:
        extract_zip(zip_path, dest_dir)

    assert "symlink" in exc_info.value.detail.lower()


def test_extract_zip_rejects_oversized_compressed(tmp_path):
    """Archives exceeding MAX_ZIP_MB should be rejected."""
    zip_path = tmp_path / "too_big.zip"
    dest_dir = tmp_path / "extracted"

    # Create a 2 MB dummy zip and set max_zip_mb=1
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("data.bin", b"0" * (2 * 1024 * 1024))

    with pytest.raises(ZipValidationError) as exc_info:
        extract_zip(zip_path, dest_dir, max_zip_mb=1)

    assert "exceeds limit" in exc_info.value.detail


def test_extract_zip_rejects_oversized_uncompressed(tmp_path):
    """Archives exceeding 3x MAX_REPO_MB uncompressed must be rejected."""
    zip_path = tmp_path / "uncompressed_too_big.zip"
    dest_dir = tmp_path / "extracted"

    # Highly compressible data
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("huge.txt", b"0" * (4 * 1024 * 1024))

    # max_repo_mb=1 -> 3x max_repo_mb = 3 MB, data is 4 MB
    with pytest.raises(ZipValidationError) as exc_info:
        extract_zip(zip_path, dest_dir, max_repo_mb=1)

    assert "exceeds limit of 3x MAX_REPO_MB" in exc_info.value.detail


def test_extract_zip_rejects_too_many_entries(tmp_path):
    """Archives exceeding 20,000 entries must be rejected."""
    zip_path = tmp_path / "many_entries.zip"
    dest_dir = tmp_path / "extracted"

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        for i in range(20005):
            zf.writestr(f"file_{i}.txt", "a")
    zip_path.write_bytes(bio.getvalue())

    with pytest.raises(ZipValidationError) as exc_info:
        extract_zip(zip_path, dest_dir)

    assert "exceeding maximum limit of 20000" in exc_info.value.detail


# ═════════════════════════════════════════════════════════════════════
# 3. iter_python_files Tests
# ═════════════════════════════════════════════════════════════════════


def test_iter_python_files_skips_vendor_and_virtualenvs(tmp_path):
    """Must find all .py files while ignoring skipped directories."""
    # Included files
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("# main")
    (tmp_path / "app" / "models.py").write_text("# models")
    (tmp_path / "setup.py").write_text("# setup")
    (tmp_path / "README.md").write_text("# doc")

    # Skipped directories
    skipped_dir_names = [
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        "site-packages",
        "build",
        "dist",
        ".tox",
    ]
    for d in skipped_dir_names:
        dir_p = tmp_path / d
        dir_p.mkdir(parents=True)
        (dir_p / "ignored.py").write_text("# ignored")

    found_files = sorted(iter_python_files(tmp_path))

    expected = sorted(["app/main.py", "app/models.py", "setup.py"])
    assert found_files == expected


def test_iter_python_files_enforces_max_files(tmp_path):
    """Must stop with an error if files exceed max_files."""
    for i in range(5):
        (tmp_path / f"test_{i}.py").write_text("# test")

    # max_files=3 on a repo with 5 files must raise
    with pytest.raises(MaxPythonFilesExceededError) as exc_info:
        list(iter_python_files(tmp_path, max_files=3))

    assert "Repository contains more than 3 Python files" in exc_info.value.detail


# ═════════════════════════════════════════════════════════════════════
# 4. find_dependency_files Tests
# ═════════════════════════════════════════════════════════════════════


def test_find_dependency_files_priority_poetry(tmp_path):
    """poetry.lock takes highest priority even if requirements.txt exists."""
    (tmp_path / "poetry.lock").write_text("poetry data")
    (tmp_path / "requirements.txt").write_text("pkg==1.0.0")
    (tmp_path / "Pipfile.lock").write_text("{}")

    res = find_dependency_files(tmp_path)
    assert res.kind == "poetry.lock"
    assert res.lockfile_kind == "poetry.lock"
    assert res.used == "poetry.lock"
    assert res.candidates == [tmp_path / "poetry.lock"]


def test_find_dependency_files_priority_requirements(tmp_path):
    """requirements*.txt takes priority when poetry.lock is absent."""
    (tmp_path / "requirements.txt").write_text("pkg==1.0.0")
    (tmp_path / "requirements-dev.txt").write_text("pytest==8.0.0")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements-prod.txt").write_text("prod==2.0.0")
    (tmp_path / "Pipfile.lock").write_text("{}")

    res = find_dependency_files(tmp_path)
    assert res.kind == "requirements.txt"
    assert res.used == "requirements.txt"

    candidate_names = [p.name for p in res.candidates]
    assert "requirements.txt" in candidate_names
    assert "requirements-dev.txt" in candidate_names
    assert "requirements-prod.txt" in candidate_names


def test_find_dependency_files_priority_pipfile(tmp_path):
    """Pipfile.lock is selected when neither poetry nor requirements exist."""
    (tmp_path / "Pipfile.lock").write_text("{}")

    res = find_dependency_files(tmp_path)
    assert res.kind == "Pipfile.lock"
    assert res.candidates == [tmp_path / "Pipfile.lock"]


def test_find_dependency_files_none_found(tmp_path):
    """Returns empty list and 'none' when no dependency files exist."""
    (tmp_path / "main.py").write_text("print('hello')")

    res = find_dependency_files(tmp_path)
    assert res.kind == "none"
    assert res.candidates == []
    assert len(res.files) == 0


# ═════════════════════════════════════════════════════════════════════
# 5. clone_repo Subprocess & Limit Tests
# ═════════════════════════════════════════════════════════════════════


@patch("subprocess.run")
def test_clone_repo_command_args_and_env(mock_subproc, tmp_path):
    """Must run exact subprocess arguments as a list (never shell=True) with GIT_TERMINAL_PROMPT=0."""
    url = "https://github.com/octocat/Hello-World"
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "sample.py").write_text("print(1)")

    clone_repo(url, dest, timeout=60, max_repo_mb=50)

    mock_subproc.assert_called_once()
    called_cmd = mock_subproc.call_args[0][0]
    called_kwargs = mock_subproc.call_args[1]

    expected_cmd = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "clone",
        "--depth",
        "200",
        "--single-branch",
        "--no-tags",
        "--filter=blob:limit=2m",
        url,
        str(dest.resolve()),
    ]
    assert called_cmd == expected_cmd
    assert called_kwargs.get("shell") is not True
    assert called_kwargs.get("timeout") == 60
    assert called_kwargs.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"


@patch("subprocess.run")
def test_clone_repo_exceeds_max_repo_mb(mock_subproc, tmp_path):
    """If repository folder size exceeds max_repo_mb, delete folder and raise error."""
    url = "https://github.com/octocat/Hello-World"
    dest = tmp_path / "dest"
    dest.mkdir()

    # Create a 2MB dummy file
    (dest / "large.bin").write_bytes(b"0" * (2 * 1024 * 1024))

    # Set max_repo_mb=1 -> should trigger deletion and error
    with pytest.raises(RepoSizeExceededError) as exc_info:
        clone_repo(url, dest, max_repo_mb=1)

    assert "exceeds maximum allowed limit" in exc_info.value.detail
    # Folder must be deleted
    assert not dest.exists()


@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=120))
def test_clone_repo_timeout(mock_subproc, tmp_path):
    """On timeout, directory is deleted and GitCloneTimeoutError raised."""
    url = "https://github.com/octocat/Hello-World"
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(GitCloneTimeoutError) as exc_info:
        clone_repo(url, dest, timeout=120)

    assert "timed out after 120 seconds" in exc_info.value.detail
    assert not dest.exists()


@patch("subprocess.run", side_effect=subprocess.CalledProcessError(returncode=128, cmd=["git"], stderr="Repository not found"))
def test_clone_repo_process_error(mock_subproc, tmp_path):
    """On git error, directory is deleted and GitCloneError raised."""
    url = "https://github.com/octocat/Hello-World"
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(GitCloneError) as exc_info:
        clone_repo(url, dest)

    assert "Repository not found" in exc_info.value.detail
    assert not dest.exists()
