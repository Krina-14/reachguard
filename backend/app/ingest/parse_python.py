"""
ReachGuard — AST-based Python source code parser.

Performs static analysis of Python source files using Python's built-in `ast` module.
NEVER imports, execs, or evals any code from the analyzed repository.

Key capabilities:
- Derives dotted module names, respecting package roots and src/ layouts.
- Extracts absolute and relative imports (resolving relative levels against current module).
- Identifies and records nested imports inside functions and try/except blocks.
- Detects dynamic imports (__import__, importlib.import_module) and flags non-literals as BlindSpots.
- Catches syntax errors gracefully and logs BlindSpot kind "unparsed_file".
- Extracts Flask and FastAPI HTTP entrypoints with methods, path prefixes, and auth heuristics.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Auth heuristic keywords ────────────────────────────────────────

AUTH_DECORATOR_KEYWORDS = (
    "login_required",
    "jwt_required",
    "auth",
    "permission",
    "requires",
)

AUTH_DEPENDS_KEYWORDS = (
    "auth",
    "current_user",
    "get_user",
    "token",
    "security",
    "verify",
    "permission",
)

HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD")


# ── Dataclasses ────────────────────────────────────────────────────


@dataclass
class ImportInfo:
    """Represents an imported module target."""

    target: str  # Dotted module name (resolved if relative)
    level: int  # 0 for absolute, >0 for relative
    line: int
    in_function: bool = False
    in_try: bool = False

    def __iter__(self) -> Iterator[Any]:
        """Allow unpacking as (target, level, line)."""
        return iter((self.target, self.level, self.line))


@dataclass
class EntrypointInfo:
    """Represents an HTTP route handler entrypoint."""

    id: str  # sha1(method|path|file)[:12]
    method: str  # HTTP method (e.g. "GET", "POST")
    path: str  # Normalized route path (e.g. "/api/users")
    file: str  # File path relative to repo root
    line: int  # Line number of the function definition
    framework: str  # "fastapi" | "flask"
    public: bool  # True if auth_hint == "none"
    auth_hint: str  # "none" | "protected"
    handler_module: str  # Dotted name of module defining handler
    handler_function: str  # Function name
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class BlindSpotInfo:
    """Represents an area where static analysis has limited visibility."""

    id: str
    kind: str  # "dynamic_import" | "unparsed_file" | "unresolved_import"
    reason: str
    file: str
    line: int
    name: str = ""


@dataclass
class ModuleInfo:
    """Complete static analysis summary of a single Python module."""

    name: str  # Dotted module name (e.g. "app.main")
    file: str  # Relative path to repo root (e.g. "app/main.py")
    lines: int  # Total lines in file
    imports: list[ImportInfo] = field(default_factory=list)
    entrypoints: list[EntrypointInfo] = field(default_factory=list)
    blind_spots: list[BlindSpotInfo] = field(default_factory=list)
    failed: bool = False


# ── Helpers ────────────────────────────────────────────────────────


def derive_module_name(rel_path: str | Path) -> str:
    """
    Derive the dotted module name from a path relative to the repo root.

    Rules:
    - Strip '.py' extension.
    - Convert directory separators '/' to '.'.
    - If a 'src/' layout exists ('src/<pkg>/...'), strip the leading 'src.'.
    - Convert '__init__' to the containing package name.
    """
    path_str = str(rel_path).replace("\\", "/").removesuffix(".py")
    parts = [p for p in path_str.split("/") if p]
    if not parts:
        return ""

    # Strip leading 'src' if part of a src layout (src/<pkg>/...)
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]

    # __init__ represents the package itself
    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def resolve_relative_import(
    current_module: str,
    rel_path: str | Path,
    level: int,
    import_module: str | None,
    alias_name: str | None = None,
) -> str:
    """
    Resolve a relative import against the current module name.

    level=1: relative to current package (from . import ...)
    level=2: relative to parent package (from .. import ...)
    """
    if level == 0:
        base = import_module or ""
        return f"{base}.{alias_name}" if (base and alias_name and not import_module) else base

    is_pkg = Path(rel_path).name == "__init__.py"
    mod_parts = [p for p in current_module.split(".") if p]

    if is_pkg:
        pkg_parts = list(mod_parts)
    else:
        pkg_parts = mod_parts[:-1] if len(mod_parts) > 1 else []

    # level 1 = 0 pops from package parts
    # level 2 = 1 pop from package parts
    pop_count = level - 1
    if pop_count >= len(pkg_parts):
        base_parts: list[str] = []
    else:
        base_parts = pkg_parts[: len(pkg_parts) - pop_count]

    if import_module:
        if base_parts:
            return ".".join(base_parts + [import_module])
        return import_module

    if alias_name:
        if base_parts:
            return ".".join(base_parts + [alias_name])
        return alias_name

    return ".".join(base_parts)


def combine_url_prefix(prefix: str, path: str) -> str:
    """Safely combine a blueprint/router prefix and a route path."""
    clean_prefix = prefix.strip()
    clean_path = path.strip()

    if not clean_prefix:
        if not clean_path.startswith("/"):
            return f"/{clean_path}"
        return clean_path

    p1 = "/" + clean_prefix.strip("/")
    p2 = clean_path.strip("/")
    if not p2:
        return p1
    return f"{p1}/{p2}"


def _make_id(*parts: str) -> str:
    """Compute 12-char SHA1 hex digest for deterministic IDs."""
    data = "|".join(parts).encode("utf-8")
    return hashlib.sha1(data).hexdigest()[:12]


def _extract_constant_str(node: ast.AST | None) -> str | None:
    """Extract string value from an ast.Constant if present."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _check_auth_heuristic(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    route_decorator: ast.AST,
    router_has_auth: bool = False,
) -> tuple[str, bool]:
    """
    Check if an entrypoint has auth guards.

    Returns:
        (auth_hint, public) where auth_hint is "protected" or "none",
        and public = (auth_hint == "none").
    """
    if router_has_auth:
        return "protected", False

    # 1. Check decorators (other than the route decorator itself)
    for dec in func_node.decorator_list:
        if dec is route_decorator:
            continue
        dec_repr = ast.unparse(dec).lower()
        if any(kw in dec_repr for kw in AUTH_DECORATOR_KEYWORDS):
            return "protected", False

    # 2. Check function parameter defaults and type annotations for Depends(...)
    # Align args with their defaults
    defaults = [None] * (len(func_node.args.args) - len(func_node.args.defaults)) + list(
        func_node.args.defaults
    )

    for arg, default in zip(func_node.args.args, defaults, strict=False):
        if default is not None:
            default_str = ast.unparse(default)
            if "Depends(" in default_str:
                default_lower = default_str.lower()
                if any(kw in default_lower for kw in AUTH_DEPENDS_KEYWORDS):
                    return "protected", False

        if arg.annotation is not None:
            ann_str = ast.unparse(arg.annotation)
            if "Depends(" in ann_str:
                ann_lower = ann_str.lower()
                if any(kw in ann_lower for kw in AUTH_DEPENDS_KEYWORDS):
                    return "protected", False

    for arg, default in zip(
        getattr(func_node.args, "kwonlyargs", []),
        getattr(func_node.args, "kw_defaults", []),
        strict=False,
    ):
        if default is not None:
            default_str = ast.unparse(default)
            if "Depends(" in default_str:
                default_lower = default_str.lower()
                if any(kw in default_lower for kw in AUTH_DEPENDS_KEYWORDS):
                    return "protected", False

        if arg.annotation is not None:
            ann_str = ast.unparse(arg.annotation)
            if "Depends(" in ann_str:
                ann_lower = ann_str.lower()
                if any(kw in ann_lower for kw in AUTH_DEPENDS_KEYWORDS):
                    return "protected", False

    # 3. Check route decorator dependencies argument e.g. dependencies=[Depends(...)]
    if isinstance(route_decorator, ast.Call):
        for kw in route_decorator.keywords:
            if kw.arg == "dependencies":
                kw_str = ast.unparse(kw.value).lower()
                if any(kw_name in kw_str for kw_name in AUTH_DEPENDS_KEYWORDS):
                    return "protected", False

    return "none", True


# ── AST Visitor ────────────────────────────────────────────────────


class PythonModuleVisitor(ast.NodeVisitor):
    """Walks the AST of a Python module to extract imports, entrypoints, and blind spots."""

    def __init__(self, code: str, rel_path: str, module_name: str) -> None:
        self.code = code
        self.rel_path = rel_path
        self.module_name = module_name

        self.imports: list[ImportInfo] = []
        self.entrypoints: list[EntrypointInfo] = []
        self.blind_spots: list[BlindSpotInfo] = []

        # Scope tracking
        self._in_function_depth = 0
        self._in_try_depth = 0

        # Router and blueprint registry (within this file)
        self.blueprint_prefixes: dict[str, str] = {}
        self.router_prefixes: dict[str, str] = {}
        self.router_has_auth: dict[str, bool] = {}

        # Detected frameworks & imported symbols
        self.file_frameworks: set[str] = set()
        self.imported_symbols: set[str] = set()

    # ── Context managers for scoping ────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_entrypoints(node)
        self._in_function_depth += 1
        self.generic_visit(node)
        self._in_function_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_entrypoints(node)
        self._in_function_depth += 1
        self.generic_visit(node)
        self._in_function_depth -= 1

    def visit_Try(self, node: ast.Try) -> None:
        self._in_try_depth += 1
        self.generic_visit(node)
        self._in_try_depth -= 1

    # ── Prefix and router discovery ─────────────────────────────────

    def visit_Assign(self, node: ast.Assign) -> None:
        # Check for: <name> = Blueprint("...", __name__, url_prefix="/...")
        # Check for: <name> = APIRouter(prefix="/...", dependencies=[Depends(...)])
        if isinstance(node.value, ast.Call):
            call = node.value
            func_name = ""
            if isinstance(call.func, ast.Name):
                func_name = call.func.id
            elif isinstance(call.func, ast.Attribute):
                func_name = call.func.attr

            # 1. Blueprint
            if func_name == "Blueprint":
                self.file_frameworks.add("flask")
                prefix = ""
                for kw in call.keywords:
                    if kw.arg == "url_prefix":
                        prefix = _extract_constant_str(kw.value) or ""
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.blueprint_prefixes[target.id] = prefix

            # 2. APIRouter
            elif func_name in ("APIRouter", "FastAPI"):
                self.file_frameworks.add("fastapi")
                prefix = ""
                has_auth = False
                for kw in call.keywords:
                    if kw.arg == "prefix":
                        prefix = _extract_constant_str(kw.value) or ""
                    elif kw.arg == "dependencies":
                        dep_repr = ast.unparse(kw.value).lower()
                        if any(k in dep_repr for k in AUTH_DEPENDS_KEYWORDS):
                            has_auth = True
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.router_prefixes[target.id] = prefix
                        if has_auth:
                            self.router_has_auth[target.id] = True

        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        # Check for: app.register_blueprint(bp, url_prefix="/override")
        if isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "register_blueprint":
                self.file_frameworks.add("flask")
                if call.args and isinstance(call.args[0], ast.Name):
                    bp_name = call.args[0].id
                    for kw in call.keywords:
                        if kw.arg == "url_prefix":
                            override = _extract_constant_str(kw.value)
                            if override is not None:
                                self.blueprint_prefixes[bp_name] = override
        self.generic_visit(node)

    # ── Import statement parsing ────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        in_fn = self._in_function_depth > 0
        in_try = self._in_try_depth > 0

        for alias in node.names:
            self.imported_symbols.add(alias.asname or alias.name)
            if alias.name in ("fastapi", "flask"):
                self.file_frameworks.add(alias.name)
            self.imports.append(
                ImportInfo(
                    target=alias.name,
                    level=0,
                    line=node.lineno,
                    in_function=in_fn,
                    in_try=in_try,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        in_fn = self._in_function_depth > 0
        in_try = self._in_try_depth > 0

        if node.module in ("fastapi", "flask"):
            self.file_frameworks.add(node.module)

        for alias in node.names:
            self.imported_symbols.add(alias.asname or alias.name)

        if node.module:
            resolved = resolve_relative_import(
                current_module=self.module_name,
                rel_path=self.rel_path,
                level=node.level,
                import_module=node.module,
            )
            self.imports.append(
                ImportInfo(
                    target=resolved,
                    level=node.level,
                    line=node.lineno,
                    in_function=in_fn,
                    in_try=in_try,
                )
            )
        else:
            # from . import foo, bar
            for alias in node.names:
                resolved = resolve_relative_import(
                    current_module=self.module_name,
                    rel_path=self.rel_path,
                    level=node.level,
                    import_module=None,
                    alias_name=alias.name,
                )
                self.imports.append(
                    ImportInfo(
                        target=resolved,
                        level=node.level,
                        line=node.lineno,
                        in_function=in_fn,
                        in_try=in_try,
                    )
                )

    # ── Dynamic imports ─────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        # Check for __import__(...) or importlib.import_module(...)
        is_dynamic = False
        func_name = ""

        if isinstance(node.func, ast.Name) and node.func.id in ("__import__", "import_module"):
            is_dynamic = True
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            is_dynamic = True
            func_name = "importlib.import_module"

        if is_dynamic and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                # Literal string -> treated as normal import
                self.imports.append(
                    ImportInfo(
                        target=first_arg.value,
                        level=0,
                        line=node.lineno,
                        in_function=self._in_function_depth > 0,
                        in_try=self._in_try_depth > 0,
                    )
                )
            else:
                # Non-literal -> BlindSpot kind "dynamic_import"
                bs_id = _make_id("dynamic_import", self.rel_path, str(node.lineno), func_name)
                arg_repr = ast.unparse(first_arg)
                self.blind_spots.append(
                    BlindSpotInfo(
                        id=bs_id,
                        kind="dynamic_import",
                        reason=f"Call to {func_name} with non-literal argument: {arg_repr}",
                        file=self.rel_path,
                        line=node.lineno,
                        name=func_name,
                    )
                )

        self.generic_visit(node)

    # ── Entrypoint identification ───────────────────────────────────

    def _check_entrypoints(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Inspect function decorators for Flask and FastAPI route declarations."""
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not isinstance(dec.func, ast.Attribute):
                continue

            attr = dec.func.attr.lower()
            receiver_name = ""
            if isinstance(dec.func.value, ast.Name):
                receiver_name = dec.func.value.id

            is_flask_route = attr == "route"
            is_http_verb = attr in ("get", "post", "put", "delete", "patch")

            if not (is_flask_route or is_http_verb):
                continue

            # Extract route path
            raw_path = "/"
            if dec.args:
                extracted = _extract_constant_str(dec.args[0])
                if extracted is not None:
                    raw_path = extracted

            # Determine HTTP methods
            methods: list[str] = []
            if is_flask_route:
                # Flask: methods=[...] keywords, default GET
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            m = _extract_constant_str(elt)
                            if m:
                                methods.append(m.upper())
                if not methods:
                    methods = ["GET"]
            else:
                # @router.get / post / ...
                methods = [attr.upper()]

            # Determine framework
            framework = "fastapi"
            if is_flask_route or receiver_name in self.blueprint_prefixes or "flask" in self.file_frameworks:
                framework = "flask"
            elif receiver_name in self.router_prefixes or "fastapi" in self.file_frameworks:
                framework = "fastapi"

            # Apply prefix resolution
            prefix = ""
            prefix_unresolved = False

            if framework == "flask":
                prefix = self.blueprint_prefixes.get(receiver_name, "")
            else:
                if receiver_name in self.router_prefixes:
                    prefix = self.router_prefixes[receiver_name]
                elif receiver_name in self.imported_symbols:
                    # Router was imported from another module -> unresolved prefix note
                    prefix_unresolved = True

            final_path = combine_url_prefix(prefix, raw_path)

            # Check auth heuristic
            router_auth = self.router_has_auth.get(receiver_name, False)
            auth_hint, public = _check_auth_heuristic(
                func_node=node,
                route_decorator=dec,
                router_has_auth=router_auth,
            )

            # Create an EntrypointInfo for each HTTP method
            for method in methods:
                ep_id = _make_id(method, final_path, self.rel_path)
                props: dict[str, Any] = {}
                if prefix_unresolved:
                    props["prefix_unresolved"] = True

                self.entrypoints.append(
                    EntrypointInfo(
                        id=ep_id,
                        method=method,
                        path=final_path,
                        file=self.rel_path,
                        line=node.lineno,
                        framework=framework,
                        public=public,
                        auth_hint=auth_hint,
                        handler_module=self.module_name,
                        handler_function=node.name,
                        props=props,
                    )
                )


# ── Public API ─────────────────────────────────────────────────────


def parse_python_source(code: str, rel_path: str) -> ModuleInfo:
    """
    Parse a Python source code string into a ModuleInfo structure.

    Never imports, execs, or evals the code.
    If a SyntaxError occurs, records a BlindSpot with kind 'unparsed_file'.
    """
    module_name = derive_module_name(rel_path)
    line_count = len(code.splitlines()) if code else 0

    try:
        tree = ast.parse(code, filename=rel_path)
    except SyntaxError as exc:
        bs_id = _make_id("unparsed_file", rel_path, str(exc.lineno or 1), exc.msg)
        return ModuleInfo(
            name=module_name,
            file=rel_path,
            lines=line_count,
            imports=[],
            entrypoints=[],
            blind_spots=[
                BlindSpotInfo(
                    id=bs_id,
                    kind="unparsed_file",
                    reason=f"SyntaxError: {exc.msg}",
                    file=rel_path,
                    line=exc.lineno or 1,
                    name=rel_path,
                )
            ],
            failed=True,
        )

    visitor = PythonModuleVisitor(code=code, rel_path=rel_path, module_name=module_name)
    visitor.visit(tree)

    return ModuleInfo(
        name=module_name,
        file=rel_path,
        lines=line_count,
        imports=visitor.imports,
        entrypoints=visitor.entrypoints,
        blind_spots=visitor.blind_spots,
        failed=False,
    )


def parse_python_file(file_path: str | Path, repo_root: str | Path) -> ModuleInfo:
    """
    Read a Python file from disk as text and parse it into a ModuleInfo structure.

    Never imports, execs, or evals the file.
    """
    path_obj = Path(file_path).resolve()
    root_obj = Path(repo_root).resolve()

    try:
        rel_path = path_obj.relative_to(root_obj).as_posix()
    except ValueError:
        rel_path = path_obj.name

    try:
        content = path_obj.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        bs_id = _make_id("unparsed_file", rel_path, "1", str(exc))
        return ModuleInfo(
            name=derive_module_name(rel_path),
            file=rel_path,
            lines=0,
            imports=[],
            entrypoints=[],
            blind_spots=[
                BlindSpotInfo(
                    id=bs_id,
                    kind="unparsed_file",
                    reason=f"Failed to read file: {exc}",
                    file=rel_path,
                    line=1,
                    name=rel_path,
                )
            ],
            failed=True,
        )

    return parse_python_source(content, rel_path)
