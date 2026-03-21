"""
JavaParser: Pure-Python Java source analyser using javalang.
Extracts classes, interfaces, Spring annotations, methods, fields,
imports, and infers the service role of each file.
Falls back to regex heuristics if javalang fails on a file.
"""
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

try:
    import javalang
    JAVALANG_AVAILABLE = True
except ImportError:
    JAVALANG_AVAILABLE = False


# Spring/Jakarta stereotype annotations we care about
SPRING_ANNOTATIONS = {
    # Web layer
    "RestController", "Controller",
    # Service layer
    "Service", "Component",
    # Data layer
    "Repository", "Entity", "Table",
    # Config
    "Configuration", "SpringBootApplication", "EnableAutoConfiguration",
    # Security
    "EnableWebSecurity",
    # Messaging
    "KafkaListener", "RabbitListener", "EventListener",
    # Scheduled
    "Scheduled", "EnableScheduling",
    # HTTP mappings
    "RequestMapping", "GetMapping", "PostMapping", "PutMapping",
    "DeleteMapping", "PatchMapping",
    # JPA
    "OneToMany", "ManyToOne", "ManyToMany", "OneToOne",
    "Id", "GeneratedValue", "Column",
    # Lombok (common)
    "Data", "Builder", "NoArgsConstructor", "AllArgsConstructor",
    "Getter", "Setter",
}

# Infer role from annotations
ROLE_MAP = {
    "RestController": "REST API controller",
    "Controller": "MVC controller",
    "Service": "Service / business logic",
    "Repository": "Data repository",
    "Entity": "JPA entity / data model",
    "Configuration": "Spring configuration",
    "SpringBootApplication": "Application entry point",
    "Component": "Spring component",
    "KafkaListener": "Kafka consumer",
    "RabbitListener": "RabbitMQ consumer",
    "EnableWebSecurity": "Security configuration",
    "Scheduled": "Scheduled task",
}


@dataclass
class MethodInfo:
    name: str
    return_type: str
    parameters: List[str]
    annotations: List[str]
    visibility: str  # public / protected / private / package


@dataclass
class FieldInfo:
    name: str
    type: str
    annotations: List[str]
    visibility: str


@dataclass
class ParsedJavaFile:
    relative_path: str
    package: Optional[str]
    class_name: Optional[str]
    class_type: str                    # class / interface / enum / abstract class
    role: str                          # inferred e.g. "REST API controller"
    annotations: List[str]
    methods: List[MethodInfo]
    fields: List[FieldInfo]
    imports: List[str]
    extends: Optional[str]
    implements: List[str]
    endpoints: List[Dict[str, str]]    # [{method, path, handler}]
    dependencies: List[str]            # @Autowired / constructor-injected types
    raw_snippet: str                   # first 60 lines for LLM context
    parse_error: Optional[str] = None


class JavaParser:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        if not JAVALANG_AVAILABLE and verbose:
            print("  [warn] javalang not installed — using regex fallback")

    def parse_files(self, java_files) -> List[ParsedJavaFile]:
        results = []
        for jf in java_files:
            parsed = self._parse_one(jf)
            results.append(parsed)
        return results

    def _parse_one(self, jf) -> ParsedJavaFile:
        if JAVALANG_AVAILABLE:
            try:
                return self._parse_with_javalang(jf)
            except Exception as e:
                # Fall through to regex
                pass
        return self._parse_with_regex(jf)

    # ------------------------------------------------------------------ #
    #  javalang-based parser                                               #
    # ------------------------------------------------------------------ #
    def _parse_with_javalang(self, jf) -> ParsedJavaFile:
        tree = javalang.parse.parse(jf.content)

        # Imports
        imports = [imp.path for imp in tree.imports] if tree.imports else []

        class_name = None
        class_type = "class"
        annotations: List[str] = []
        methods: List[MethodInfo] = []
        fields: List[FieldInfo] = []
        extends_cls = None
        implements_list: List[str] = []
        endpoints: List[Dict[str, str]] = []
        dependencies: List[str] = []

        # Find primary type declaration
        type_decl = None
        for path, node in tree:
            if isinstance(node, (javalang.tree.ClassDeclaration,
                                  javalang.tree.InterfaceDeclaration,
                                  javalang.tree.EnumDeclaration)):
                type_decl = node
                break

        if type_decl is None:
            raise ValueError("No type declaration found")

        class_name = type_decl.name
        if isinstance(type_decl, javalang.tree.InterfaceDeclaration):
            class_type = "interface"
        elif isinstance(type_decl, javalang.tree.EnumDeclaration):
            class_type = "enum"
        elif type_decl.modifiers and "abstract" in type_decl.modifiers:
            class_type = "abstract class"

        # Class-level annotations
        if type_decl.annotations:
            for ann in type_decl.annotations:
                annotations.append(ann.name)

        # Extends / implements
        if hasattr(type_decl, "extends") and type_decl.extends:
            ext = type_decl.extends
            if isinstance(ext, list):
                extends_cls = ext[0].name if ext else None
            else:
                extends_cls = ext.name if hasattr(ext, "name") else str(ext)

        if hasattr(type_decl, "implements") and type_decl.implements:
            implements_list = [i.name for i in type_decl.implements if hasattr(i, "name")]

        # Fields
        if hasattr(type_decl, "fields") and type_decl.fields:
            for f in type_decl.fields:
                f_anns = [a.name for a in f.annotations] if f.annotations else []
                vis = self._visibility(f.modifiers)
                f_type = f.type.name if hasattr(f.type, "name") else str(f.type)
                for decl in f.declarators:
                    fields.append(FieldInfo(
                        name=decl.name,
                        type=f_type,
                        annotations=f_anns,
                        visibility=vis,
                    ))
                    # Detect autowired dependencies
                    if "Autowired" in f_anns or "Inject" in f_anns:
                        dependencies.append(f_type)

        # Methods
        if hasattr(type_decl, "methods") and type_decl.methods:
            for m in type_decl.methods:
                m_anns = [a.name for a in m.annotations] if m.annotations else []
                ret = m.return_type.name if m.return_type and hasattr(m.return_type, "name") else "void"
                params = []
                if m.parameters:
                    for p in m.parameters:
                        p_type = p.type.name if hasattr(p.type, "name") else str(p.type)
                        params.append(f"{p_type} {p.name}")

                methods.append(MethodInfo(
                    name=m.name,
                    return_type=ret,
                    parameters=params,
                    annotations=m_anns,
                    visibility=self._visibility(m.modifiers),
                ))

                # Extract HTTP endpoints
                for http_ann in ("GetMapping", "PostMapping", "PutMapping",
                                  "DeleteMapping", "PatchMapping", "RequestMapping"):
                    if http_ann in m_anns:
                        path = self._extract_mapping_path(m.annotations, http_ann)
                        endpoints.append({
                            "method": http_ann.replace("Mapping", "").upper()
                                      if http_ann != "RequestMapping" else "ANY",
                            "path": path,
                            "handler": m.name,
                        })

        # Constructor injection: look for constructors with params
        if hasattr(type_decl, "constructors") and type_decl.constructors:
            for ctor in type_decl.constructors:
                if ctor.parameters and len(ctor.parameters) > 0:
                    for p in ctor.parameters:
                        p_type = p.type.name if hasattr(p.type, "name") else str(p.type)
                        if p_type[0].isupper():   # heuristic: type name starts with uppercase
                            dependencies.append(p_type)

        role = self._infer_role(annotations, class_name or "")
        snippet = "\n".join(jf.content.splitlines()[:60])

        return ParsedJavaFile(
            relative_path=jf.relative_path,
            package=jf.package,
            class_name=class_name,
            class_type=class_type,
            role=role,
            annotations=annotations,
            methods=methods,
            fields=fields,
            imports=imports,
            extends=extends_cls,
            implements=implements_list,
            endpoints=endpoints,
            dependencies=list(set(dependencies)),
            raw_snippet=snippet,
        )

    # ------------------------------------------------------------------ #
    #  Regex fallback parser                                               #
    # ------------------------------------------------------------------ #
    def _parse_with_regex(self, jf) -> ParsedJavaFile:
        content = jf.content
        lines = content.splitlines()

        # Package
        package = jf.package

        # Imports
        imports = re.findall(r'^import\s+([\w.]+);', content, re.MULTILINE)

        # Annotations on class
        annotations = re.findall(r'@(\w+)', content[:2000])
        annotations = [a for a in annotations if a in SPRING_ANNOTATIONS]

        # Class name and type
        class_match = re.search(
            r'\b(public\s+)?(abstract\s+)?(class|interface|enum)\s+(\w+)', content
        )
        class_name = class_match.group(4) if class_match else None
        raw_type = class_match.group(3) if class_match else "class"
        is_abstract = "abstract" in (class_match.group(2) or "") if class_match else False
        class_type = ("abstract class" if is_abstract else raw_type) if class_match else "class"

        # Extends / implements
        extends_match = re.search(r'\bextends\s+(\w+)', content[:3000])
        extends_cls = extends_match.group(1) if extends_match else None

        impl_match = re.search(r'\bimplements\s+([\w\s,]+?)(?:\{|extends)', content[:3000])
        implements_list = []
        if impl_match:
            implements_list = [i.strip() for i in impl_match.group(1).split(",") if i.strip()]

        # Methods (public only via regex)
        methods: List[MethodInfo] = []
        method_pattern = re.compile(
            r'(?:@(\w+)\s+)*'
            r'(public|protected|private)?\s+'
            r'(?:static\s+|final\s+|synchronized\s+)*'
            r'(\w[\w<>\[\],\s]*?)\s+'
            r'(\w+)\s*\(([^)]*)\)',
            re.MULTILINE
        )
        for m in method_pattern.finditer(content):
            mname = m.group(4)
            if mname in ("if", "while", "for", "switch", "catch"):
                continue
            ret = (m.group(3) or "void").strip()
            params_raw = m.group(5) or ""
            params = [p.strip() for p in params_raw.split(",") if p.strip()]
            vis = m.group(2) or "package"
            methods.append(MethodInfo(
                name=mname, return_type=ret, parameters=params,
                annotations=[], visibility=vis,
            ))

        # Endpoints
        endpoints: List[Dict[str, str]] = []
        for http_verb in ("GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping"):
            for m in re.finditer(rf'@{http_verb}\s*\(\s*["\']([^"\']+)["\']', content):
                # Find nearest method
                after = content[m.end():]
                nm = re.search(r'\b(\w+)\s*\(', after[:200])
                endpoints.append({
                    "method": http_verb.replace("Mapping", "").upper(),
                    "path": m.group(1),
                    "handler": nm.group(1) if nm else "unknown",
                })

        # Autowired dependencies
        dep_matches = re.findall(r'@(?:Autowired|Inject)\s+(?:private\s+)?(\w+)\s+\w+', content)
        dependencies = list(set(dep_matches))

        role = self._infer_role(annotations, class_name or "")
        snippet = "\n".join(lines[:60])

        return ParsedJavaFile(
            relative_path=jf.relative_path,
            package=package,
            class_name=class_name,
            class_type=class_type,
            role=role,
            annotations=annotations,
            methods=methods,
            fields=[],
            imports=imports,
            extends=extends_cls,
            implements=implements_list,
            endpoints=endpoints,
            dependencies=dependencies,
            raw_snippet=snippet,
            parse_error="regex_fallback",
        )

    def _visibility(self, modifiers) -> str:
        if not modifiers:
            return "package"
        for v in ("public", "protected", "private"):
            if v in modifiers:
                return v
        return "package"

    def _infer_role(self, annotations: List[str], class_name: str) -> str:
        for ann in annotations:
            if ann in ROLE_MAP:
                return ROLE_MAP[ann]
        # Name heuristics
        n = class_name.lower()
        if n.endswith("controller"): return "REST API controller"
        if n.endswith("service"):    return "Service / business logic"
        if n.endswith("repository") or n.endswith("dao"): return "Data repository"
        if n.endswith("entity") or n.endswith("model"):   return "Data model"
        if n.endswith("config") or n.endswith("configuration"): return "Configuration"
        if n.endswith("exception"):  return "Exception type"
        if n.endswith("dto") or n.endswith("request") or n.endswith("response"): return "DTO / transfer object"
        if n.endswith("util") or n.endswith("helper") or n.endswith("utils"): return "Utility"
        if n.endswith("test") or n.startswith("test"): return "Test class"
        return "Component"

    def _extract_mapping_path(self, annotations, ann_name: str) -> str:
        if annotations:
            for a in annotations:
                if a.name == ann_name:
                    if a.element:
                        el = a.element
                        if hasattr(el, "value"):
                            return str(el.value).strip('"\'')
                        if isinstance(el, list) and el:
                            return str(el[0]).strip('"\'')
        return "/"
