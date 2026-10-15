"""
ReachGuard — Lockfile and dependency specifications parser.

Parses dependency files into a normalized LockResult:
- requirements*.txt: handles version pinning, extras, markers, recursive -r includes, and unpinned packages.
- poetry.lock: parses via standard library `tomllib`, extracts package versions and dependency graph edges.
- Pipfile.lock: parses JSON default dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# PEP 503 normalization regex
PEP_503_NORMALIZE_RE = re.compile(r"[-_.]+")


def normalize_name(name: str) -> str:
    """Normalize a package name according to PEP 503 (lowercase, dashes)."""
    return PEP_503_NORMALIZE_RE.sub("-", name).strip().lower()


@dataclass
class PackageSpec:
    """Represents a declared package dependency."""

    name: str  # PEP 503 normalized name
    version: str | None  # Pinned version string, or None if unpinned
    direct: bool = True  # True if directly declared by user project

    def __getitem__(self, item: str) -> Any:
        if item == "name":
            return self.name
        if item == "version":
            return self.version
        if item == "direct":
            return self.direct
        raise KeyError(item)


@dataclass
class LockResult:
    """Unified result of scanning lockfiles or requirements files."""

    kind: str  # "requirements.txt" | "poetry.lock" | "Pipfile.lock"
    packages: list[PackageSpec] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from_package_id, to_package_id)
    transitive_available: bool = False
    unpinned: list[str] = field(default_factory=list)
    unsupported_lines: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        if item == "kind":
            return self.kind
        if item == "packages":
            return self.packages
        if item == "edges":
            return self.edges
        if item == "transitive_available":
            return self.transitive_available
        if item == "unpinned":
            return self.unpinned
        if item == "unsupported_lines":
            return self.unsupported_lines
        if item == "flags":
            return self.flags
        raise KeyError(item)


# ── Requirements.txt Parser ────────────────────────────────────────


def parse_requirements_text(
    text: str,
    base_dir: Path | None = None,
    depth: int = 0,
    seen_files: set[Path] | None = None,
) -> LockResult:
    """
    Parse content of a requirements.txt file.

    Handles:
    - name==version
    - names with extras: name[extra]==1.0
    - environment markers after ';'
    - comments and blank lines
    - -r include directives (resolved relative to base_dir, max depth 3)
    - records unsupported lines: starting with -e, git+, http://, https://
    - unpinned lines (e.g. flask>=2): returned with version=None and added to unpinned
    - PEP 503 normalization
    """
    if seen_files is None:
        seen_files = set()

    packages_map: dict[str, PackageSpec] = {}
    unpinned: list[str] = []
    unsupported_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Strip inline comments (e.g. "pkg==1.0 # comment")
        line = re.split(r"\s+#", line)[0].strip()
        if not line:
            continue

        # Check unsupported directives
        if line.startswith(("-e", "--editable", "git+", "http://", "https://")):
            unsupported_lines.append(raw_line.strip())
            continue

        # Handle -r include directives
        if line.startswith(("-r ", "--requirement ", "-r=")):
            parts = line.split(maxsplit=1)
            include_ref = parts[1].strip() if len(parts) > 1 else line.split("=", 1)[1].strip()

            if depth < 3 and base_dir is not None:
                inc_path = (base_dir / include_ref).resolve()
                if inc_path.is_file() and inc_path not in seen_files:
                    seen_files.add(inc_path)
                    try:
                        inc_text = inc_path.read_text(encoding="utf-8", errors="replace")
                        sub_res = parse_requirements_text(
                            inc_text,
                            base_dir=inc_path.parent,
                            depth=depth + 1,
                            seen_files=seen_files,
                        )
                        for pkg in sub_res.packages:
                            packages_map[pkg.name] = pkg
                        unpinned.extend(sub_res.unpinned)
                        unsupported_lines.extend(sub_res.unsupported_lines)
                    except OSError as exc:
                        logger.warning("Could not read included requirements file %s: %s", inc_path, exc)
            else:
                unsupported_lines.append(raw_line.strip())
            continue

        # Ignore other pip configuration flags (-i, -f, etc.)
        if line.startswith(("-", "--")):
            unsupported_lines.append(raw_line.strip())
            continue

        # Strip environment markers after ';'
        spec_part = line.split(";", 1)[0].strip()

        # Parse package name and extras: e.g. "requests[security]==2.28.1"
        if "==" in spec_part:
            name_part, ver_part = spec_part.split("==", 1)
            raw_name = name_part.split("[")[0].strip()
            norm_name = normalize_name(raw_name)
            ver = ver_part.strip()
            # Clean possible trailing quotes or comments
            ver = re.split(r"[\s,;]", ver)[0].strip().strip("\"'")
            packages_map[norm_name] = PackageSpec(name=norm_name, version=ver, direct=True)
        else:
            # Lines without '==' (e.g. flask>=2, urllib3) -> unpinned
            name_part = re.split(r"[><=~!]", spec_part)[0].strip()
            raw_name = name_part.split("[")[0].strip()
            norm_name = normalize_name(raw_name)
            packages_map[norm_name] = PackageSpec(name=norm_name, version=None, direct=True)
            if norm_name not in unpinned:
                unpinned.append(norm_name)

    return LockResult(
        kind="requirements.txt",
        packages=list(packages_map.values()),
        edges=[],
        transitive_available=False,
        unpinned=unpinned,
        unsupported_lines=unsupported_lines,
    )


def parse_requirements(path: str | Path) -> LockResult:
    """Read and parse a requirements file from disk."""
    file_path = Path(path).resolve()
    text = file_path.read_text(encoding="utf-8", errors="replace")
    seen = {file_path}
    return parse_requirements_text(text, base_dir=file_path.parent, depth=0, seen_files=seen)


# ── Poetry Lock Parser ─────────────────────────────────────────────


def parse_poetry_lock_text(
    lock_text: str,
    pyproject_text: str | None = None,
) -> LockResult:
    """
    Parse a poetry.lock TOML document.

    Extracts:
    - [[package]] entries: name, version
    - [package.dependencies]: gives DEPENDS_ON edges
    - Direct packages from pyproject_text's [tool.poetry.dependencies] if present
      else marks direct=False and flags 'direct_unknown'.
    """
    data = tomllib.loads(lock_text)

    # 1. Determine direct dependencies from pyproject.toml if supplied
    direct_packages: set[str] = set()
    has_pyproject = False
    flags: list[str] = []

    if pyproject_text:
        try:
            pyproject_data = tomllib.loads(pyproject_text)
            has_pyproject = True

            # Standard poetry 1.x: [tool.poetry.dependencies]
            tool_poetry = pyproject_data.get("tool", {}).get("poetry", {})
            poetry_deps = tool_poetry.get("dependencies", {})
            for k in poetry_deps:
                if k.lower() != "python":
                    direct_packages.add(normalize_name(k))

            # Poetry 2.x / PEP 621: [project.dependencies]
            project_deps = pyproject_data.get("project", {}).get("dependencies", [])
            if isinstance(project_deps, list):
                for dep in project_deps:
                    raw_n = re.split(r"[><=~!;\s\[]", dep)[0].strip()
                    if raw_n:
                        direct_packages.add(normalize_name(raw_n))

            # Also check group dependencies e.g. [tool.poetry.group.main.dependencies]
            groups = tool_poetry.get("group", {})
            for grp_data in groups.values():
                for k in grp_data.get("dependencies", {}):
                    if k.lower() != "python":
                        direct_packages.add(normalize_name(k))

        except (tomllib.TOMLDecodeError, OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse pyproject.toml: %s", exc)
            has_pyproject = False

    if not has_pyproject:
        flags.append("direct_unknown")

    # 2. Extract packages
    package_list: list[PackageSpec] = []
    pkg_version_map: dict[str, str] = {}
    raw_edges: list[tuple[str, str]] = []

    for pkg in data.get("package", []):
        raw_name = pkg.get("name", "")
        version = pkg.get("version", "")
        if not raw_name:
            continue

        norm_name = normalize_name(raw_name)
        pkg_version_map[norm_name] = version

        is_direct = (norm_name in direct_packages) if has_pyproject else False
        package_list.append(PackageSpec(name=norm_name, version=version, direct=is_direct))

        # Dependencies
        deps = pkg.get("dependencies", {})
        if isinstance(deps, dict):
            for dep_raw_name in deps:
                dep_norm = normalize_name(dep_raw_name)
                raw_edges.append((norm_name, dep_norm))

    # 3. Build edges as (from_id, to_id) where id is name@version
    edges: list[tuple[str, str]] = []
    for from_pkg, to_pkg in raw_edges:
        from_ver = pkg_version_map.get(from_pkg, "unknown")
        to_ver = pkg_version_map.get(to_pkg, "unknown")
        from_id = f"{from_pkg}@{from_ver}"
        to_id = f"{to_pkg}@{to_ver}"
        edges.append((from_id, to_id))

    return LockResult(
        kind="poetry.lock",
        packages=package_list,
        edges=edges,
        transitive_available=True,
        unpinned=[],
        unsupported_lines=[],
        flags=flags,
    )


def parse_poetry_lock(path: str | Path) -> LockResult:
    """Read and parse poetry.lock and check for sibling pyproject.toml."""
    lock_file = Path(path).resolve()
    lock_text = lock_file.read_text(encoding="utf-8", errors="replace")

    pyproject_file = lock_file.parent / "pyproject.toml"
    pyproject_text = None
    if pyproject_file.is_file():
        pyproject_text = pyproject_file.read_text(encoding="utf-8", errors="replace")

    return parse_poetry_lock_text(lock_text, pyproject_text=pyproject_text)


# ── Pipfile.lock Parser ────────────────────────────────────────────


def parse_pipfile_lock_text(json_text: str) -> LockResult:
    """
    Parse a Pipfile.lock JSON document.

    Reads 'default' section. Versions are formatted like '==1.2.3'.
    No dependency edges are available in Pipfile.lock.
    """
    data = json.loads(json_text)
    default_section = data.get("default", {})

    packages: list[PackageSpec] = []
    unpinned: list[str] = []

    for raw_name, details in default_section.items():
        norm_name = normalize_name(raw_name)
        ver_spec = details.get("version", "")
        if ver_spec.startswith("=="):
            version = ver_spec[2:].strip()
        else:
            version = ver_spec.strip() or None
            unpinned.append(norm_name)

        packages.append(PackageSpec(name=norm_name, version=version, direct=True))

    return LockResult(
        kind="Pipfile.lock",
        packages=packages,
        edges=[],
        transitive_available=False,
        unpinned=unpinned,
        unsupported_lines=[],
    )


def parse_pipfile_lock(path: str | Path) -> LockResult:
    """Read and parse a Pipfile.lock file from disk."""
    file_path = Path(path).resolve()
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return parse_pipfile_lock_text(text)
