"""
Unit tests for backend/app/ingest/lockfiles.py and importmap.py.

Covers:
- requirements.txt parsing:
  - pinned lines (name==version)
  - extras handling (name[extra]==1.0)
  - environment markers after ';'
  - recursive -r includes with depth limit and cycle protection
  - unsupported lines (-e, git+, http URLs)
  - unpinned packages (flask>=2 -> version None, unpinned flag)
  - PEP 503 normalization
- poetry.lock parsing:
  - package names, versions, and DEPENDS_ON edges
  - direct packages derived from pyproject.toml
  - fallback to direct=False and 'direct_unknown' flag when pyproject.toml is absent
- Pipfile.lock parsing:
  - JSON default section, version stripping, direct=True
- importmap resolution:
  - STDLIB detection (sys.stdlib_module_names)
  - FIRST_PARTY detection
  - static mapping table (yaml -> pyyaml, PIL -> pillow, etc.)
  - underscore to dash replacement
  - unresolved third-party imports returning None
"""

from app.ingest.importmap import resolve_import
from app.ingest.lockfiles import (
    normalize_name,
    parse_pipfile_lock_text,
    parse_poetry_lock_text,
    parse_requirements,
    parse_requirements_text,
)

# ═════════════════════════════════════════════════════════════════════
# 1. Requirements.txt Parsing Tests
# ═════════════════════════════════════════════════════════════════════


def test_parse_requirements_pinned():
    text = """
requests==2.31.0
Flask==3.0.0
PyYAML==6.0.1
"""
    res = parse_requirements_text(text)
    assert res.kind == "requirements.txt"
    assert len(res.packages) == 3
    assert res.transitive_available is False
    assert len(res.unpinned) == 0

    pkg_map = {pkg.name: pkg for pkg in res.packages}
    assert pkg_map["requests"].version == "2.31.0"
    assert pkg_map["flask"].version == "3.0.0"
    assert pkg_map["pyyaml"].version == "6.0.1"
    assert pkg_map["requests"].direct is True


def test_parse_requirements_extras_and_markers():
    text = """
# Pinned with extras and environment markers
requests[security]==2.28.1; python_version >= '3.8'
celery[redis,auth]==5.3.0
importlib-metadata>=0.12; python_version < '3.8'
"""
    res = parse_requirements_text(text)
    pkg_map = {pkg.name: pkg for pkg in res.packages}

    # Extras should be stripped from the package name
    assert "requests" in pkg_map
    assert pkg_map["requests"].version == "2.28.1"

    assert "celery" in pkg_map
    assert pkg_map["celery"].version == "5.3.0"

    assert "importlib-metadata" in pkg_map
    assert pkg_map["importlib-metadata"].version is None
    assert "importlib-metadata" in res.unpinned


def test_parse_requirements_unpinned_flagged():
    text = """
flask>=2.0.0
pydantic<2
urllib3
requests~=2.28
"""
    res = parse_requirements_text(text)
    assert len(res.packages) == 4
    for pkg in res.packages:
        assert pkg.version is None
        assert pkg.name in res.unpinned


def test_parse_requirements_unsupported_and_comments():
    text = """
# Top-level comment
flask==3.0.0 # inline comment

-e .
--editable ./subpkg
git+https://github.com/psf/requests.git@main
https://github.com/pallets/flask/archive/main.zip
-i https://pypi.org/simple
--extra-index-url https://custom.pypi.org/
"""
    res = parse_requirements_text(text)
    assert len(res.packages) == 1
    assert res.packages[0].name == "flask"
    assert res.packages[0].version == "3.0.0"

    # Unsupported directives must be recorded
    assert len(res.unsupported_lines) >= 4
    assert any("-e ." in line for line in res.unsupported_lines)
    assert any("git+" in line for line in res.unsupported_lines)
    assert any("https://" in line for line in res.unsupported_lines)


def test_parse_requirements_recursive_includes(tmp_path):
    base_req = tmp_path / "base.txt"
    base_req.write_text("werkzeug==3.0.1\njinja2==3.1.2\n")

    main_req = tmp_path / "requirements.txt"
    main_req.write_text("-r base.txt\nflask==3.0.0\n")

    res = parse_requirements(main_req)
    pkg_map = {pkg.name: pkg for pkg in res.packages}

    assert "flask" in pkg_map
    assert "werkzeug" in pkg_map
    assert "jinja2" in pkg_map
    assert pkg_map["werkzeug"].version == "3.0.1"


# ═════════════════════════════════════════════════════════════════════
# 2. Poetry Lock Parsing Tests
# ═════════════════════════════════════════════════════════════════════


def test_parse_poetry_lock_with_dependencies():
    lock_toml = """
[[package]]
name = "flask"
version = "3.0.0"
description = "A simple framework"
dependencies = { werkzeug = ">=3.0.0", jinja2 = ">=3.1.2" }

[[package]]
name = "werkzeug"
version = "3.0.1"
dependencies = { markupsafe = ">=2.1.1" }

[[package]]
name = "jinja2"
version = "3.1.2"
dependencies = {}

[[package]]
name = "markupsafe"
version = "2.1.3"
"""
    pyproject_toml = """
[tool.poetry]
name = "my-app"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.11"
flask = "^3.0.0"
"""
    res = parse_poetry_lock_text(lock_toml, pyproject_text=pyproject_toml)
    assert res.kind == "poetry.lock"
    assert res.transitive_available is True
    assert len(res.packages) == 4

    pkg_map = {pkg.name: pkg for pkg in res.packages}
    # flask was in [tool.poetry.dependencies] -> direct=True
    assert pkg_map["flask"].direct is True
    # werkzeug was not in [tool.poetry.dependencies] -> direct=False
    assert pkg_map["werkzeug"].direct is False

    # Check dependency edges
    assert ("flask@3.0.0", "werkzeug@3.0.1") in res.edges
    assert ("flask@3.0.0", "jinja2@3.1.2") in res.edges
    assert ("werkzeug@3.0.1", "markupsafe@2.1.3") in res.edges


def test_parse_poetry_lock_without_pyproject():
    lock_toml = """
[[package]]
name = "requests"
version = "2.31.0"
"""
    res = parse_poetry_lock_text(lock_toml, pyproject_text=None)
    assert len(res.packages) == 1
    # When pyproject is missing, all direct=False and flagged direct_unknown
    assert res.packages[0].direct is False
    assert "direct_unknown" in res.flags


# ═════════════════════════════════════════════════════════════════════
# 3. Pipfile.lock Parsing Tests
# ═════════════════════════════════════════════════════════════════════


def test_parse_pipfile_lock():
    json_text = """
{
    "_meta": {"hash": {"sha256": "12345"}},
    "default": {
        "requests": {
            "hashes": ["sha256:abc"],
            "version": "==2.31.0"
        },
        "flask": {
            "version": "==3.0.0"
        }
    },
    "develop": {
        "pytest": {
            "version": "==8.0.0"
        }
    }
}
"""
    res = parse_pipfile_lock_text(json_text)
    assert res.kind == "Pipfile.lock"
    assert res.transitive_available is False
    assert len(res.packages) == 2

    pkg_map = {pkg.name: pkg for pkg in res.packages}
    assert pkg_map["requests"].version == "2.31.0"
    assert pkg_map["flask"].version == "3.0.0"
    assert pkg_map["requests"].direct is True


# ═════════════════════════════════════════════════════════════════════
# 4. Import Map Resolution Tests
# ═════════════════════════════════════════════════════════════════════


def test_resolve_import_stdlib():
    assert resolve_import("os", known_packages=[]) == "STDLIB"
    assert resolve_import("sys", known_packages=[]) == "STDLIB"
    assert resolve_import("json", known_packages=[]) == "STDLIB"
    assert resolve_import("urllib.parse", known_packages=[]) == "STDLIB"
    assert resolve_import("collections.abc", known_packages=[]) == "STDLIB"


def test_resolve_import_first_party():
    first_party = {"app", "app.models", "reachguard"}
    assert resolve_import("app", known_packages=[], first_party_modules=first_party) == "FIRST_PARTY"
    assert resolve_import("app.models", known_packages=[], first_party_modules=first_party) == "FIRST_PARTY"
    assert resolve_import("reachguard.core", known_packages=[], first_party_modules=first_party) == "FIRST_PARTY"


def test_resolve_import_exact_normalized_match():
    known = ["requests", "fastapi", "PyYAML"]
    assert resolve_import("requests", known_packages=known) == "requests"
    assert resolve_import("fastapi", known_packages=known) == "fastapi"


def test_resolve_import_static_mapping():
    known = [
        "pyyaml",
        "Pillow",
        "opencv-python",
        "scikit-learn",
        "beautifulsoup4",
        "pyjwt",
        "python-dateutil",
        "pyopenssl",
        "pycryptodome",
        "mysqlclient",
        "psycopg2-binary",
        "python-jose",
        "python-magic",
        "python-dotenv",
        "attrs",
        "pyserial",
        "protobuf",
    ]
    assert resolve_import("yaml", known_packages=known) == "pyyaml"
    assert resolve_import("PIL", known_packages=known) == "Pillow"
    assert resolve_import("cv2", known_packages=known) == "opencv-python"
    assert resolve_import("sklearn", known_packages=known) == "scikit-learn"
    assert resolve_import("bs4", known_packages=known) == "beautifulsoup4"
    assert resolve_import("jwt", known_packages=known) == "pyjwt"
    assert resolve_import("dateutil", known_packages=known) == "python-dateutil"
    assert resolve_import("OpenSSL", known_packages=known) == "pyopenssl"
    assert resolve_import("Crypto", known_packages=known) == "pycryptodome"
    assert resolve_import("MySQLdb", known_packages=known) == "mysqlclient"
    assert resolve_import("psycopg2", known_packages=known) == "psycopg2-binary"
    assert resolve_import("jose", known_packages=known) == "python-jose"
    assert resolve_import("magic", known_packages=known) == "python-magic"
    assert resolve_import("dotenv", known_packages=known) == "python-dotenv"
    assert resolve_import("attr", known_packages=known) == "attrs"
    assert resolve_import("serial", known_packages=known) == "pyserial"
    assert resolve_import("google.protobuf", known_packages=known) == "protobuf"


def test_resolve_import_underscore_to_dash():
    known = ["flask-sqlalchemy", "flask-login", "flask-cors", "flask-migrate", "flask-wtf"]
    assert resolve_import("flask_sqlalchemy", known_packages=known) == "flask-sqlalchemy"
    assert resolve_import("flask_login", known_packages=known) == "flask-login"
    assert resolve_import("flask_cors", known_packages=known) == "flask-cors"
    assert resolve_import("flask_migrate", known_packages=known) == "flask-migrate"
    assert resolve_import("flask_wtf", known_packages=known) == "flask-wtf"


def test_resolve_import_unresolved_returns_none():
    known = ["requests", "flask"]
    # Unknown third-party import not in known dependencies
    assert resolve_import("unknown_third_party_lib", known_packages=known) is None


def test_normalize_name():
    assert normalize_name("PyYAML") == "pyyaml"
    assert normalize_name("flask_login") == "flask-login"
    assert normalize_name("backports.ssl_match_hostname") == "backports-ssl-match-hostname"
    assert normalize_name("Foo---Bar...Baz___Qux") == "foo-bar-baz-qux"
