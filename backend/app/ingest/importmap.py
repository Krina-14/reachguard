"""
ReachGuard — Import to Package Distribution Resolution Map.

Provides translation from Python module import names (e.g. `import yaml`) to
their corresponding PyPI distribution names (e.g. `pyyaml`).

Resolution precedence:
1. Standard library modules -> "STDLIB"
2. First-party repo modules -> "FIRST_PARTY"
3. Exact normalized match in known_packages
4. Static mapping table translation
5. Normalized match after replacing '_' with '-'
6. None (unresolved)
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable

# PEP 503 normalization regex
PEP_503_NORMALIZE_RE = re.compile(r"[-_.]+")


def normalize_name(name: str) -> str:
    """Normalize a package or module name according to PEP 503."""
    return PEP_503_NORMALIZE_RE.sub("-", name).strip().lower()


# ═════════════════════════════════════════════════════════════════════
# CONFIGURATION TABLE (STATIC MAPPING), NOT RUNTIME/USER DATA.
# Maps Python top-level import names to their PyPI distribution package names.
# ═════════════════════════════════════════════════════════════════════

IMPORT_TO_DIST_MAP: dict[str, str] = {
    # Prompt specified mappings
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "jwt": "pyjwt",
    "dateutil": "python-dateutil",
    "OpenSSL": "pyopenssl",
    "Crypto": "pycryptodome",
    "MySQLdb": "mysqlclient",
    "psycopg2": "psycopg2-binary",
    "flask_sqlalchemy": "flask-sqlalchemy",
    "flask_login": "flask-login",
    "flask_wtf": "flask-wtf",
    "flask_cors": "flask-cors",
    "flask_migrate": "flask-migrate",
    "jose": "python-jose",
    "magic": "python-magic",
    "dotenv": "python-dotenv",
    "attr": "attrs",
    "serial": "pyserial",
    "google.protobuf": "protobuf",
    "protobuf": "protobuf",
    # Additional industry-standard mismatches
    "git": "gitpython",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "pymupdf",
    "Bio": "biopython",
    "OpenGL": "pyopengl",
    "websocket": "websocket-client",
    "multipart": "python-multipart",
    "pkg_resources": "setuptools",
    "setuptools": "setuptools",
    "yaml_env_tag": "yaml-env-tag",
    "sentry_sdk": "sentry-sdk",
    "pydantic_settings": "pydantic-settings",
    "pydantic_core": "pydantic-core",
    "falkordb": "falkordb",
    "redis": "redis",
    "fastapi": "fastapi",
    "starlette": "starlette",
    "slowapi": "slowapi",
    "httpx": "httpx",
    "requests": "requests",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "celery": "celery",
    "boto3": "boto3",
    "botocore": "botocore",
    "cryptography": "cryptography",
    "bcrypt": "bcrypt",
    "uvicorn": "uvicorn",
}


def resolve_import(
    top_level_name: str,
    known_packages: Iterable[str],
    first_party_modules: set[str] | None = None,
) -> str | None:
    """
    Resolve an imported module name against known dependencies.

    Precedence:
    - Standard library modules -> "STDLIB"
    - First-party modules -> "FIRST_PARTY"
    - 1) Exact normalized match in known_packages
    - 2) Static mapping table translation
    - 3) Normalized match after replacing '_' with '-'
    - 4) None (unresolved)
    """
    if not top_level_name:
        return None

    # Handle dotted module paths (e.g. 'os.path' -> 'os', 'yaml.loader' -> 'yaml')
    root_import = top_level_name.split(".")[0]

    # 1. Standard library check (Python 3.10+ sys.stdlib_module_names)
    if (
        root_import in sys.stdlib_module_names
        or top_level_name in sys.stdlib_module_names
    ):
        return "STDLIB"

    # 2. First-party module check
    if first_party_modules and (
        top_level_name in first_party_modules
        or root_import in first_party_modules
    ):
        return "FIRST_PARTY"

    # Build normalized lookup map from known_packages: normalized -> original
    known_map: dict[str, str] = {
        normalize_name(p): p for p in known_packages
    }

    # 3. Exact normalized match: e.g. "requests" -> "requests"
    norm_import = normalize_name(root_import)
    if norm_import in known_map:
        return known_map[norm_import]

    # Also check full dotted name if package has dots (e.g. backports.zoneinfo)
    norm_full = normalize_name(top_level_name)
    if norm_full in known_map:
        return known_map[norm_full]

    # 4. Mapping table: e.g. "yaml" -> "pyyaml", "PIL" -> "pillow"
    mapped_dist = (
        IMPORT_TO_DIST_MAP.get(top_level_name)
        or IMPORT_TO_DIST_MAP.get(root_import)
        or IMPORT_TO_DIST_MAP.get(norm_import)
    )
    if mapped_dist:
        norm_mapped = normalize_name(mapped_dist)
        if norm_mapped in known_map:
            return known_map[norm_mapped]

    # 5. Normalized match after replacing '_' with '-'
    alt_name = normalize_name(root_import.replace("_", "-"))
    if alt_name in known_map:
        return known_map[alt_name]

    # 6. Unresolved
    return None
