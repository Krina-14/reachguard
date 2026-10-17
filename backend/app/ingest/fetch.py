"""
ReachGuard — Ingestion fetch and repository source utilities.

Functions:
- validate_git_url: strictly validates GitHub repository URLs against MVP constraints.
- clone_repo: executes git clone safely in a subprocess with size and timeout guards.
- extract_zip: extracts zip archives with zip-bomb, zip-slip, and symlink protection.
- iter_python_files: yields relative paths of .py files, pruning virtualenvs and vendor dirs.
- find_dependency_files: discovers lockfile candidates in priority order and reports used kind.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

# ── GitHub URL validation ──────────────────────────────────────────
# Accepts ONLY: ^https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})(\.git)?/?$
GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})(\.git)?/?$"
)

# ── Directories excluded during Python file searches ───────────────
SKIP_DIRS = frozenset(
    {
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
    }
)

# Maximum allowed entries in a zip archive
MAX_ZIP_ENTRIES = 20000


# ── Exceptions ─────────────────────────────────────────────────────


class GitUrlValidationError(HTTPException, ValueError):
    """Raised when a git repository URL fails validation constraints (HTTP 422)."""

    def __init__(
        self,
        detail: str = "Invalid GitHub repository URL. Format must be 'https://github.com/<owner>/<repo>'",
    ):
        super().__init__(
            status_code=422, detail=detail
        )


class GitCloneError(HTTPException, RuntimeError):
    """Raised when git clone subprocess fails."""

    def __init__(
        self,
        detail: str = "Git clone failed",
        status_code: int = 400,
    ):
        super().__init__(status_code=status_code, detail=detail)


class GitCloneTimeoutError(GitCloneError):
    """Raised when git clone subprocess times out."""

    def __init__(self, detail: str = "Git clone timed out"):
        super().__init__(detail=detail, status_code=408)


class RepoSizeExceededError(HTTPException, ValueError):
    """Raised when repository folder size exceeds configured limit."""

    def __init__(self, detail: str = "Repository size exceeds configured limit"):
        super().__init__(
            status_code=413, detail=detail
        )


class ZipValidationError(HTTPException, ValueError):
    """Raised when a zip archive fails safety or integrity checks."""

    def __init__(self, detail: str = "Invalid zip archive"):
        super().__init__(
            status_code=422, detail=detail
        )


class MaxPythonFilesExceededError(HTTPException, ValueError):
    """Raised when repository contains more Python files than allowed."""

    def __init__(
        self, detail: str = "Repository exceeds maximum allowed Python files"
    ):
        super().__init__(
            status_code=413, detail=detail
        )


# ── Dependency scan result ─────────────────────────────────────────


class DependencyFilesResult(NamedTuple):
    """Result of searching for dependency/lockfile candidates."""

    candidates: list[Path]
    kind: str  # "poetry.lock" | "requirements.txt" | "Pipfile.lock" | "none"

    @property
    def files(self) -> list[Path]:
        return self.candidates

    @property
    def lockfile_kind(self) -> str:
        return self.kind

    @property
    def used(self) -> str:
        return self.kind


# ── Helper functions ───────────────────────────────────────────────


def compute_dir_size_bytes(dir_path: Path) -> int:
    """Compute total size of regular files in directory in bytes."""
    total = 0
    for root, _, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ── Core fetch functions ───────────────────────────────────────────


def validate_git_url(url: str) -> tuple[str, str]:
    """
    Validate a Git repository URL.

    Accepts ONLY:
      ^https://github\\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})(\\.git)?/?$

    Anything else raises a validation error (HTTP 422).
    No other hosts, no schemes other than https, no credentials, no query strings.

    Returns:
        (owner, repo) tuple.
    """
    if not isinstance(url, str):
        raise GitUrlValidationError("Git URL must be a string")

    match = GITHUB_URL_PATTERN.match(url)
    if not match:
        raise GitUrlValidationError(
            f"Invalid GitHub URL: {url!r}. Only 'https://github.com/<owner>/<repo>' is accepted."
        )

    owner = match.group(1)
    repo = match.group(2)

    # Strip optional .git suffix if captured in repo name
    repo = repo.removesuffix(".git")

    return owner, repo


def clone_repo(
    url: str,
    dest_dir: str | Path,
    timeout: int = 120,
    max_repo_mb: int | None = None,
) -> Path:
    """
    Clone a GitHub repository safely into dest_dir.

    Subprocess command list (never shell=True):
      ["git", "-c", "core.hooksPath=/dev/null", "clone", "--depth", "200",
       "--single-branch", "--no-tags", "--filter=blob:limit=2m", url, dest]

    Sets GIT_TERMINAL_PROMPT=0.
    Enforces timeout.
    Computes folder size and deletes destination + raises error if > MAX_REPO_MB.
    """
    validate_git_url(url)

    if max_repo_mb is None:
        max_repo_mb = settings.MAX_REPO_MB

    dest = Path(dest_dir).resolve()
    dest_str = str(dest)

    cmd = [
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
        dest_str,
    ]

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        subprocess.run(
            cmd,
            env=env,
            timeout=timeout,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        logger.error("Git clone timed out after %ds for %s", timeout, url)
        raise GitCloneTimeoutError(
            f"Git clone timed out after {timeout} seconds"
        ) from exc
    except subprocess.CalledProcessError as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        err_msg = exc.stderr.strip() if exc.stderr else str(exc)
        logger.error("Git clone failed for %s: %s", url, err_msg)
        raise GitCloneError(f"Git clone failed: {err_msg}") from exc

    # Compute folder size and check limit
    size_bytes = compute_dir_size_bytes(dest)
    size_mb = size_bytes / (1024 * 1024)

    if size_mb > max_repo_mb:
        shutil.rmtree(dest, ignore_errors=True)
        logger.warning(
            "Repository size %.1f MB exceeds MAX_REPO_MB (%d MB). Deleted %s",
            size_mb,
            max_repo_mb,
            dest,
        )
        raise RepoSizeExceededError(
            f"Repository size ({size_mb:.1f} MB) exceeds maximum allowed limit of {max_repo_mb} MB"
        )

    return dest


def extract_zip(
    zip_path: str | Path,
    dest_dir: str | Path,
    max_zip_mb: int | None = None,
    max_repo_mb: int | None = None,
) -> Path:
    """
    Safely extract a zip archive into dest_dir.

    Guards:
    - Reject if compressed size > MAX_ZIP_MB.
    - Reject if total uncompressed size > 3x MAX_REPO_MB.
    - Reject any member whose resolved path is outside dest_dir (zip-slip: absolute paths, "..").
    - Reject symlinks.
    - Reject if more than 20,000 entries.
    """
    if max_zip_mb is None:
        max_zip_mb = settings.MAX_ZIP_MB
    if max_repo_mb is None:
        max_repo_mb = settings.MAX_REPO_MB

    zip_file = Path(zip_path).resolve()
    if not zip_file.is_file():
        raise ZipValidationError(f"Zip file does not exist: {zip_file}")

    # 1. Check compressed size
    compressed_bytes = zip_file.stat().st_size
    max_compressed_bytes = max_zip_mb * 1024 * 1024
    if compressed_bytes > max_compressed_bytes:
        raise ZipValidationError(
            f"Zip archive compressed size ({compressed_bytes / (1024 * 1024):.1f} MB) "
            f"exceeds limit of {max_zip_mb} MB"
        )

    dest = Path(dest_dir).resolve()
    max_uncompressed_bytes = 3 * max_repo_mb * 1024 * 1024

    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            infolist = zf.infolist()

            # 2. Reject more than 20,000 entries
            if len(infolist) > MAX_ZIP_ENTRIES:
                raise ZipValidationError(
                    f"Zip archive contains {len(infolist)} entries, exceeding maximum limit of {MAX_ZIP_ENTRIES}"
                )

            # 3. Check declared total uncompressed size
            total_uncompressed = sum(info.file_size for info in infolist)
            if total_uncompressed > max_uncompressed_bytes:
                raise ZipValidationError(
                    f"Zip uncompressed size ({total_uncompressed / (1024 * 1024):.1f} MB) "
                    f"exceeds limit of 3x MAX_REPO_MB ({3 * max_repo_mb} MB)"
                )

            # 4. Validate all members before extracting any file
            for info in infolist:
                # Check for symlinks
                # Mode in high 16 bits of external_attr
                file_mode = info.external_attr >> 16
                if file_mode and stat.S_ISLNK(file_mode):
                    raise ZipValidationError(
                        f"Zip archive contains symlink member: '{info.filename}', which is not allowed"
                    )

                # Check for zip-slip: absolute paths, drive letters, parent traversals
                member_name = info.filename
                if member_name.startswith(("/", "\\")):
                    raise ZipValidationError(
                        f"Zip-slip detected: member '{member_name}' has absolute path"
                    )

                parts = Path(member_name).parts
                if any(p == ".." for p in parts):
                    raise ZipValidationError(
                        f"Zip-slip detected: member '{member_name}' contains '..' parent directory traversal"
                    )

                target_path = (dest / member_name).resolve()
                try:
                    target_path.relative_to(dest)
                except ValueError as exc:
                    raise ZipValidationError(
                        f"Zip-slip detected: member '{member_name}' resolves outside destination directory"
                    ) from exc

            # 5. Extract safely and verify streamed uncompressed bytes
            dest.mkdir(parents=True, exist_ok=True)
            extracted_bytes = 0

            for info in infolist:
                target_path = (dest / info.filename).resolve()
                if info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target_path, "wb") as dst:
                        while chunk := src.read(65536):
                            extracted_bytes += len(chunk)
                            if extracted_bytes > max_uncompressed_bytes:
                                shutil.rmtree(dest, ignore_errors=True)
                                raise ZipValidationError(
                                    f"Uncompressed data exceeded 3x MAX_REPO_MB ({3 * max_repo_mb} MB) during extraction"
                                )
                            dst.write(chunk)

    except zipfile.BadZipFile as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise ZipValidationError(f"Invalid or corrupted zip archive: {exc}") from exc
    except Exception:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise

    return dest


def iter_python_files(
    root: str | Path,
    max_files: int | None = None,
) -> Iterator[str]:
    """
    Yield relative paths of *.py files within root.

    Skips directories named:
      .git, node_modules, venv, .venv, env, __pycache__, site-packages, build, dist, .tox.

    Raises MaxPythonFilesExceededError if count exceeds MAX_PY_FILES.
    """
    if max_files is None:
        max_files = settings.MAX_PY_FILES

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return

    count = 0
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune skipped directories and symlinks in-place
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))
        ]

        for fname in sorted(filenames):
            if fname.endswith(".py"):
                full_path = os.path.join(dirpath, fname)
                if os.path.islink(full_path):
                    continue

                count += 1
                if count > max_files:
                    raise MaxPythonFilesExceededError(
                        f"Repository contains more than {max_files} Python files"
                    )

                rel_path = os.path.relpath(full_path, root_path)
                yield Path(rel_path).as_posix()


def find_dependency_files(root: str | Path) -> DependencyFilesResult:
    """
    Find best lockfile candidates in priority order:
      1. poetry.lock (at repo root or one level deep)
      2. requirements*.txt (all at repo root and one level deep)
      3. Pipfile.lock (at repo root or one level deep)

    Returns DependencyFilesResult(candidates=[...], kind="...") and logs the selected kind.
    If none found, returns candidates=[] and kind="none".
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        logger.warning("Root path is not a directory: %s", root_path)
        return DependencyFilesResult(candidates=[], kind="none")

    # 1. Priority: poetry.lock
    poetry_root = root_path / "poetry.lock"
    if poetry_root.is_file() and not poetry_root.is_symlink():
        logger.info("Selected lockfile: poetry.lock at %s", poetry_root)
        return DependencyFilesResult(candidates=[poetry_root], kind="poetry.lock")

    # Check one level deep for poetry.lock if not at root
    for entry in sorted(root_path.iterdir()):
        if entry.is_dir() and not entry.is_symlink() and entry.name not in SKIP_DIRS:
            poetry_sub = entry / "poetry.lock"
            if poetry_sub.is_file() and not poetry_sub.is_symlink():
                logger.info("Selected lockfile: poetry.lock at %s", poetry_sub)
                return DependencyFilesResult(candidates=[poetry_sub], kind="poetry.lock")

    # 2. Priority: requirements*.txt (all at repo root and one level deep)
    req_candidates: list[Path] = []

    # Root requirements*.txt
    root_reqs = sorted(
        [
            p
            for p in root_path.glob("requirements*.txt")
            if p.is_file() and not p.is_symlink()
        ]
    )
    # Prefer exact "requirements.txt" first if present
    exact_root = root_path / "requirements.txt"
    if exact_root in root_reqs:
        root_reqs.remove(exact_root)
        root_reqs.insert(0, exact_root)
    req_candidates.extend(root_reqs)

    # One level deep requirements*.txt
    for entry in sorted(root_path.iterdir()):
        if entry.is_dir() and not entry.is_symlink() and entry.name not in SKIP_DIRS:
            sub_reqs = sorted(
                [
                    p
                    for p in entry.glob("requirements*.txt")
                    if p.is_file() and not p.is_symlink()
                ]
            )
            exact_sub = entry / "requirements.txt"
            if exact_sub in sub_reqs:
                sub_reqs.remove(exact_sub)
                sub_reqs.insert(0, exact_sub)
            req_candidates.extend(sub_reqs)

    if req_candidates:
        logger.info(
            "Selected dependency files: requirements.txt (%d candidates found: %s)",
            len(req_candidates),
            [str(p.relative_to(root_path)) for p in req_candidates],
        )
        return DependencyFilesResult(
            candidates=req_candidates, kind="requirements.txt"
        )

    # 3. Priority: Pipfile.lock
    pipfile_root = root_path / "Pipfile.lock"
    if pipfile_root.is_file() and not pipfile_root.is_symlink():
        logger.info("Selected lockfile: Pipfile.lock at %s", pipfile_root)
        return DependencyFilesResult(candidates=[pipfile_root], kind="Pipfile.lock")

    for entry in sorted(root_path.iterdir()):
        if entry.is_dir() and not entry.is_symlink() and entry.name not in SKIP_DIRS:
            pipfile_sub = entry / "Pipfile.lock"
            if pipfile_sub.is_file() and not pipfile_sub.is_symlink():
                logger.info("Selected lockfile: Pipfile.lock at %s", pipfile_sub)
                return DependencyFilesResult(
                    candidates=[pipfile_sub], kind="Pipfile.lock"
                )

    # 4. None found
    logger.info("No lockfile or requirements candidates found in %s", root_path)
    return DependencyFilesResult(candidates=[], kind="none")
