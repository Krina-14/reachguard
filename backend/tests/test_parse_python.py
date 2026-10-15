"""
Unit tests for backend/app/ingest/parse_python.py.

Covers:
- Flask route with methods list (and default GET)
- Flask Blueprint prefix and register_blueprint override
- FastAPI route with Depends auth and router-level dependencies
- Heuristic auth hints (login_required, jwt_required, auth, etc.)
- Relative import resolution against current module
- Nested imports inside functions (in_function=True) and try/except (in_try=True)
- Dynamic import flagging (non-literal __import__ and importlib.import_module)
- Literal importlib.import_module treated as normal import
- Syntax error recording as BlindSpot "unparsed_file"
- Module name derivation for standard and src/ layouts
"""

from app.ingest.parse_python import (
    derive_module_name,
    parse_python_source,
    resolve_relative_import,
)

# ═════════════════════════════════════════════════════════════════════
# 1. Module Name Derivation Tests
# ═════════════════════════════════════════════════════════════════════


def test_derive_module_name_standard():
    assert derive_module_name("app/main.py") == "app.main"
    assert derive_module_name("app/auth/security.py") == "app.auth.security"
    assert derive_module_name("app/__init__.py") == "app"
    assert derive_module_name("app/ingest/__init__.py") == "app.ingest"
    assert derive_module_name("main.py") == "main"
    assert derive_module_name("api/v1/routes.py") == "api.v1.routes"


def test_derive_module_name_src_layout():
    assert derive_module_name("src/reachguard/main.py") == "reachguard.main"
    assert derive_module_name("src/reachguard/__init__.py") == "reachguard"
    assert derive_module_name("src/pkg/sub/tool.py") == "pkg.sub.tool"


def test_derive_module_name_windows_paths():
    assert derive_module_name("app\\api\\users.py") == "app.api.users"
    assert derive_module_name("src\\my_pkg\\utils.py") == "my_pkg.utils"


# ═════════════════════════════════════════════════════════════════════
# 2. Flask Route & Blueprint Tests
# ═════════════════════════════════════════════════════════════════════


def test_flask_route_with_methods():
    code = """
from flask import Flask
app = Flask(__name__)

@app.route("/items", methods=["GET", "POST"])
def manage_items():
    return "ok"

@app.route("/default")
def default_route():
    return "default"
"""
    info = parse_python_source(code, "app/views.py")
    assert not info.failed
    assert len(info.entrypoints) == 3

    ep_map = {(ep.method, ep.path): ep for ep in info.entrypoints}
    assert ("GET", "/items") in ep_map
    assert ("POST", "/items") in ep_map
    assert ("GET", "/default") in ep_map

    ep_get = ep_map[("GET", "/items")]
    assert ep_get.framework == "flask"
    assert ep_get.public is True
    assert ep_get.auth_hint == "none"
    assert ep_get.handler_module == "app.views"
    assert ep_get.handler_function == "manage_items"


def test_flask_blueprint_prefix():
    code = """
from flask import Blueprint

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

@bp.route("/users")
def list_users():
    return "users"
"""
    info = parse_python_source(code, "app/routes.py")
    assert len(info.entrypoints) == 1
    ep = info.entrypoints[0]
    assert ep.path == "/api/v1/users"
    assert ep.method == "GET"
    assert ep.framework == "flask"


def test_flask_blueprint_override_prefix():
    code = """
from flask import Flask, Blueprint

app = Flask(__name__)
bp = Blueprint("auth", __name__, url_prefix="/auth")
app.register_blueprint(bp, url_prefix="/api/auth")

@bp.route("/login", methods=["POST"])
def login():
    return "login"
"""
    info = parse_python_source(code, "app/auth.py")
    assert len(info.entrypoints) == 1
    ep = info.entrypoints[0]
    # Overridden prefix /api/auth + /login -> /api/auth/login
    assert ep.path == "/api/auth/login"
    assert ep.method == "POST"


# ═════════════════════════════════════════════════════════════════════
# 3. FastAPI Route & Auth Heuristic Tests
# ═════════════════════════════════════════════════════════════════════


def test_fastapi_route_with_depends_auth():
    code = """
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/profile")

@router.get("/me")
def get_profile(user=Depends(get_current_user)):
    return user
"""
    info = parse_python_source(code, "app/api/profile.py")
    assert len(info.entrypoints) == 1
    ep = info.entrypoints[0]
    assert ep.path == "/profile/me"
    assert ep.method == "GET"
    assert ep.framework == "fastapi"
    assert ep.auth_hint == "protected"
    assert ep.public is False


def test_fastapi_router_level_auth_dependency():
    code = """
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/admin", dependencies=[Depends(verify_token)])

@router.get("/dashboard")
def dashboard():
    return "secret"
"""
    info = parse_python_source(code, "app/admin.py")
    assert len(info.entrypoints) == 1
    ep = info.entrypoints[0]
    assert ep.path == "/admin/dashboard"
    assert ep.auth_hint == "protected"
    assert ep.public is False


def test_fastapi_public_route():
    code = """
from fastapi import APIRouter

router = APIRouter(prefix="/api")

@router.get("/health")
def health():
    return {"status": "ok"}
"""
    info = parse_python_source(code, "app/health.py")
    assert len(info.entrypoints) == 1
    ep = info.entrypoints[0]
    assert ep.path == "/api/health"
    assert ep.auth_hint == "none"
    assert ep.public is True


def test_auth_decorator_heuristics():
    code = """
from flask import Flask
app = Flask(__name__)

@app.route("/secret")
@login_required
def secret_view():
    return "secret"

@app.route("/jwt-view")
@jwt_required()
def jwt_view():
    return "jwt"
"""
    info = parse_python_source(code, "app/views.py")
    assert len(info.entrypoints) == 2
    for ep in info.entrypoints:
        assert ep.auth_hint == "protected"
        assert ep.public is False


def test_fastapi_imported_router_unresolved_flag():
    code = """
from app.routers import shared_router

@shared_router.get("/endpoint")
def my_endpoint():
    return "ok"
"""
    info = parse_python_source(code, "app/handlers.py")
    assert len(info.entrypoints) == 1
    ep = info.entrypoints[0]
    assert ep.props.get("prefix_unresolved") is True


# ═════════════════════════════════════════════════════════════════════
# 4. Import & Relative Import Resolution Tests
# ═════════════════════════════════════════════════════════════════════


def test_relative_import_resolution():
    assert (
        resolve_relative_import("app.api.users", "app/api/users.py", 1, "models")
        == "app.api.models"
    )
    assert (
        resolve_relative_import("app.api.users", "app/api/users.py", 2, "core")
        == "app.core"
    )
    assert (
        resolve_relative_import("app.api.users", "app/api/users.py", 1, None, "sibling")
        == "app.api.sibling"
    )
    assert (
        resolve_relative_import("app", "app/__init__.py", 1, "config")
        == "app.config"
    )


def test_import_parsing_with_function_and_try_flags():
    code = """
import os
from sys import path

def my_func():
    import json
    return json.dumps({})

try:
    import tomllib
except ImportError:
    import toml as tomllib
"""
    info = parse_python_source(code, "app/sample.py")
    imports = info.imports

    target_map = {imp.target: imp for imp in imports}
    assert "os" in target_map
    assert not target_map["os"].in_function
    assert not target_map["os"].in_try

    assert "json" in target_map
    assert target_map["json"].in_function is True

    assert "tomllib" in target_map
    assert target_map["tomllib"].in_try is True

    assert "toml" in target_map
    assert target_map["toml"].in_try is True


# ═════════════════════════════════════════════════════════════════════
# 5. Dynamic Imports & Syntax Errors Tests
# ═════════════════════════════════════════════════════════════════════


def test_dynamic_import_flagged():
    code = """
import importlib

plugin_name = "custom_auth"
mod = importlib.import_module(plugin_name)
other = __import__(f"plugins.{plugin_name}")
"""
    info = parse_python_source(code, "app/plugins.py")
    assert len(info.blind_spots) == 2
    for bs in info.blind_spots:
        assert bs.kind == "dynamic_import"
        assert bs.file == "app/plugins.py"
        assert "non-literal" in bs.reason.lower()


def test_literal_importlib_accepted():
    code = """
import importlib

# Literal string arguments should be treated as normal imports
auth_mod = importlib.import_module("app.auth.security")
sys_mod = __import__("sys")
"""
    info = parse_python_source(code, "app/loader.py")
    # No blind spots because string literals are statically resolvable
    assert len(info.blind_spots) == 0

    targets = [imp.target for imp in info.imports]
    assert "app.auth.security" in targets
    assert "sys" in targets


def test_syntax_error_becomes_unparsed_file():
    bad_code = """
def broken_function(:
    print("missing parameter name")
"""
    info = parse_python_source(bad_code, "app/broken.py")
    assert info.failed is True
    assert len(info.blind_spots) == 1

    bs = info.blind_spots[0]
    assert bs.kind == "unparsed_file"
    assert bs.file == "app/broken.py"
    assert "SyntaxError" in bs.reason
    assert bs.line >= 1
