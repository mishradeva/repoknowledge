"""
PythonParser: Pure stdlib AST-based parser for Python source files.
Extracts:
  - Classes (with bases, decorators, methods, attributes)
  - Functions / async functions (with args, return type hints, decorators)
  - Imports (import + from-import)
  - Framework detection: FastAPI, Flask, Django, Celery, SQLAlchemy, Pydantic
  - Route endpoints (@app.get, @router.post, @app.route, etc.)
  - Dependency injection patterns (FastAPI Depends)
"""
import ast
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


# Framework annotation / decorator patterns we care about
FRAMEWORK_DECORATORS = {
    # FastAPI
    "get", "post", "put", "delete", "patch", "options", "head",
    "router.get", "router.post", "router.put", "router.delete", "router.patch",
    "app.get", "app.post", "app.put", "app.delete", "app.patch",
    # Flask
    "route", "app.route", "blueprint.route",
    # Django
    "login_required", "permission_required", "csrf_exempt",
    "api_view",
    # Celery
    "task", "shared_task", "app.task",
    # SQLAlchemy / Pydantic
    "validates", "event.listens_for",
    # General Python
    "property", "staticmethod", "classmethod", "abstractmethod",
    "dataclass", "pytest.fixture", "pytest.mark",
}

ROLE_MAP = {
    "APIRouter": "FastAPI router",
    "FastAPI": "FastAPI application",
    "Flask": "Flask application",
    "Blueprint": "Flask blueprint",
    "BaseModel": "Pydantic model / DTO",
    "SQLModel": "SQLModel entity",
    "Base": "SQLAlchemy ORM model",
    "DeclarativeBase": "SQLAlchemy ORM model",
    "AsyncSession": "Database session handler",
    "Celery": "Celery task queue",
    "TestCase": "Unit test",
    "AsyncTestCase": "Async unit test",
}


@dataclass
class FunctionInfo:
    name: str
    args: List[str]
    return_type: Optional[str]
    decorators: List[str]
    is_async: bool
    is_method: bool
    docstring: Optional[str]
    lineno: int


@dataclass
class ClassInfo:
    name: str
    bases: List[str]
    decorators: List[str]
    methods: List[FunctionInfo]
    attributes: List[str]          # class-level assignments
    docstring: Optional[str]


@dataclass
class ParsedPythonFile:
    relative_path: str
    module_name: str               # derived from path
    role: str
    classes: List[ClassInfo]
    functions: List[FunctionInfo]  # top-level functions
    imports: List[str]
    from_imports: Dict[str, List[str]]   # {module: [names]}
    endpoints: List[Dict[str, str]]      # [{method, path, handler}]
    frameworks: List[str]
    docstring: Optional[str]
    raw_snippet: str
    parse_error: Optional[str] = None


class PythonParser:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def parse_files(self, py_files) -> List[ParsedPythonFile]:
        results = []
        for pf in py_files:
            parsed = self._parse_one(pf)
            results.append(parsed)
        return results

    def _parse_one(self, pf) -> ParsedPythonFile:
        try:
            return self._parse_with_ast(pf)
        except SyntaxError as e:
            return self._fallback(pf, str(e))

    def _parse_with_ast(self, pf) -> ParsedPythonFile:
        tree = ast.parse(pf.content, filename=pf.relative_path)

        module_docstring = ast.get_docstring(tree)
        imports: List[str] = []
        from_imports: Dict[str, List[str]] = {}
        classes: List[ClassInfo] = []
        functions: List[FunctionInfo] = []
        endpoints: List[Dict[str, str]] = []
        frameworks: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    fw = self._detect_framework(alias.name)
                    if fw:
                        frameworks.append(fw)

            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [a.name for a in node.names]
                from_imports.setdefault(mod, []).extend(names)
                fw = self._detect_framework(mod)
                if fw:
                    frameworks.append(fw)

        # Top-level class and function definitions
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                cls = self._extract_class(node)
                classes.append(cls)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = self._extract_function(node, is_method=False)
                functions.append(fn)
                ep = self._extract_endpoint(fn)
                if ep:
                    endpoints.append(ep)

        # Endpoints from class methods too
        for cls in classes:
            for method in cls.methods:
                ep = self._extract_endpoint(method)
                if ep:
                    endpoints.append(ep)

        frameworks = list(dict.fromkeys(frameworks))  # dedupe, preserve order
        role = self._infer_role(classes, functions, frameworks, pf.relative_path)
        snippet = "\n".join(pf.content.splitlines()[:60])

        return ParsedPythonFile(
            relative_path=pf.relative_path,
            module_name=self._path_to_module(pf.relative_path),
            role=role,
            classes=classes,
            functions=functions,
            imports=imports,
            from_imports=from_imports,
            endpoints=endpoints,
            frameworks=frameworks,
            docstring=module_docstring,
            raw_snippet=snippet,
        )

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        bases = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(f"{self._unparse_attr(b)}")

        decorators = [self._unparse_decorator(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        methods: List[FunctionInfo] = []
        attributes: List[str] = []

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._extract_function(item, is_method=True))
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attributes.append(target.id)
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    annotation = self._unparse_annotation(item.annotation)
                    attributes.append(f"{item.target.id}: {annotation}")

        return ClassInfo(
            name=node.name,
            bases=bases,
            decorators=decorators,
            methods=methods,
            attributes=attributes[:20],
            docstring=docstring,
        )

    def _extract_function(self, node, is_method: bool = False) -> FunctionInfo:
        args = []
        for arg in node.args.args:
            if arg.arg == "self" or arg.arg == "cls":
                continue
            annotation = self._unparse_annotation(arg.annotation) if arg.annotation else ""
            args.append(f"{arg.arg}: {annotation}" if annotation else arg.arg)

        return_type = self._unparse_annotation(node.returns) if node.returns else None
        decorators = [self._unparse_decorator(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)

        return FunctionInfo(
            name=node.name,
            args=args[:8],
            return_type=return_type,
            decorators=decorators,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_method=is_method,
            docstring=docstring,
            lineno=node.lineno,
        )

    def _extract_endpoint(self, fn: FunctionInfo) -> Optional[Dict[str, str]]:
        """Detect FastAPI/Flask route decorators."""
        http_methods = {"get", "post", "put", "delete", "patch", "options", "head"}
        for dec in fn.decorators:
            # FastAPI / Flask style: @app.get("/path") or @router.post("/path")
            m = re.match(r'(?:\w+\.)?(\w+)\(["\']([^"\']+)["\']', dec)
            if m:
                verb = m.group(1).lower()
                path = m.group(2)
                if verb in http_methods:
                    return {"method": verb.upper(), "path": path,
                            "handler": fn.name, "description": fn.docstring or ""}
            # @route("/path", methods=["GET"])
            m2 = re.match(r'(?:\w+\.)?route\(["\']([^"\']+)["\'].*methods=\[([^\]]+)\]', dec)
            if m2:
                path = m2.group(1)
                methods_raw = m2.group(2)
                for verb in http_methods:
                    if verb.upper() in methods_raw.upper():
                        return {"method": verb.upper(), "path": path,
                                "handler": fn.name, "description": fn.docstring or ""}
                return {"method": "ANY", "path": path,
                        "handler": fn.name, "description": fn.docstring or ""}
        return None

    def _detect_framework(self, module_name: str) -> Optional[str]:
        fw_map = {
            "fastapi": "FastAPI",
            "flask": "Flask",
            "django": "Django",
            "starlette": "Starlette",
            "aiohttp": "aiohttp",
            "sqlalchemy": "SQLAlchemy",
            "sqlmodel": "SQLModel",
            "pydantic": "Pydantic",
            "celery": "Celery",
            "pytest": "pytest",
            "unittest": "unittest",
            "alembic": "Alembic",
            "redis": "Redis",
            "motor": "MongoDB (motor)",
            "pymongo": "MongoDB",
            "boto3": "AWS (boto3)",
            "kafka": "Kafka",
        }
        base = module_name.split(".")[0].lower()
        return fw_map.get(base)

    def _infer_role(self, classes, functions, frameworks, path: str) -> str:
        path_lower = path.lower()

        # Check class bases for well-known types
        all_bases = [b for cls in classes for b in cls.bases]
        for base, role in ROLE_MAP.items():
            if base in all_bases:
                return role

        # Path heuristics
        if "router" in path_lower or "route" in path_lower:
            return "API router"
        if "endpoint" in path_lower or "view" in path_lower:
            return "API endpoint / view"
        if "model" in path_lower or "schema" in path_lower:
            return "Data model / schema"
        if "service" in path_lower:
            return "Service / business logic"
        if "repository" in path_lower or "dao" in path_lower or "crud" in path_lower:
            return "Data repository / CRUD"
        if "test" in path_lower or path_lower.startswith("test_"):
            return "Test module"
        if "config" in path_lower or "setting" in path_lower:
            return "Configuration"
        if "util" in path_lower or "helper" in path_lower:
            return "Utility"
        if "task" in path_lower or "worker" in path_lower:
            return "Background task / worker"
        if "middleware" in path_lower:
            return "Middleware"
        if "__init__" in path_lower:
            return "Package init"
        if "main" in path_lower or "app" in path_lower:
            if any(fw in frameworks for fw in ["FastAPI", "Flask", "Django"]):
                return "Application entry point"

        if frameworks:
            return f"{frameworks[0]} module"
        return "Python module"

    def _path_to_module(self, rel_path: str) -> str:
        return rel_path.replace("/", ".").replace("\\", ".").removesuffix(".py")

    def _unparse_decorator(self, node) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return self._unparse_attr(node)
            return "decorator"

    def _unparse_annotation(self, node) -> str:
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            if isinstance(node, ast.Name):
                return node.id
            return "Any"

    def _unparse_attr(self, node) -> str:
        if isinstance(node, ast.Attribute):
            return f"{self._unparse_attr(node.value)}.{node.attr}"
        if isinstance(node, ast.Name):
            return node.id
        return "?"

    def _fallback(self, pf, error: str) -> ParsedPythonFile:
        """Regex fallback for files with syntax errors."""
        content = pf.content
        imports = re.findall(r'^import\s+([\w.]+)', content, re.MULTILINE)
        from_imports_raw = re.findall(r'^from\s+([\w.]+)\s+import', content, re.MULTILINE)
        classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
        functions = re.findall(r'^(?:async\s+)?def\s+(\w+)', content, re.MULTILINE)

        return ParsedPythonFile(
            relative_path=pf.relative_path,
            module_name=self._path_to_module(pf.relative_path),
            role="Python module",
            classes=[],
            functions=[],
            imports=imports,
            from_imports={m: [] for m in from_imports_raw},
            endpoints=[],
            frameworks=[],
            docstring=None,
            raw_snippet="\n".join(content.splitlines()[:60]),
            parse_error=f"SyntaxError: {error}",
        )
