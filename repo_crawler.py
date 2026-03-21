"""
RepoCrawler: Walks a local repo and returns relevant files.
Skips binaries, build artifacts, test dirs (configurable), node_modules etc.
Implements SHA-256 hash caching so unchanged files are skipped on re-runs.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field


# Directories to always skip
SKIP_DIRS = {
    ".git", ".github", "node_modules", "__pycache__", ".idea", ".vscode",
    "build", "target", "out", ".gradle", ".mvn", "dist", "bin", "obj",
    ".terraform", ".cache", "coverage", ".nyc_output", "vendor",
}

# Infra file patterns
INFRA_PATTERNS = {
    "dockerfile": ["Dockerfile", "Dockerfile.*", "*.dockerfile"],
    "docker_compose": ["docker-compose.yml", "docker-compose.yaml", "compose.yml"],
    "kubernetes": ["*.yaml", "*.yml"],  # filtered further by content
    "terraform": ["*.tf", "*.tfvars"],
    "github_actions": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"],
    "properties": ["application.properties", "application.yml", "application.yaml",
                   "application-*.properties", "application-*.yml"],
    "spring_boot": ["bootstrap.yml", "bootstrap.yaml", "bootstrap.properties"],
}


@dataclass
class JavaFile:
    path: Path
    relative_path: str
    content: str
    sha256: str
    size_bytes: int
    package: Optional[str] = None


@dataclass
class PythonFile:
    path: Path
    relative_path: str
    content: str
    sha256: str
    size_bytes: int


@dataclass
class TypeScriptFile:
    path: Path
    relative_path: str
    content: str
    sha256: str
    size_bytes: int
    file_type: str   # ".ts" | ".tsx" | ".js"


@dataclass
class InfraFile:
    path: Path
    relative_path: str
    content: str
    category: str  # dockerfile, kubernetes, terraform, maven, etc.


class RepoCrawler:
    def __init__(self, repo_root: Path, max_files: int = 100, cache_file: str = ".repowiki_cache.json"):
        self.repo_root = repo_root
        self.max_files = max_files
        self.cache_path = repo_root / cache_file
        self.cache: Dict[str, str] = self._load_cache()

    def _load_cache(self) -> Dict[str, str]:
        """Load file hash cache to skip unchanged files."""
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        try:
            self.cache_path.write_text(json.dumps(self.cache, indent=2))
        except Exception:
            pass

    def _sha256(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def _should_skip_dir(self, dir_path: Path) -> bool:
        for part in dir_path.parts:
            if part in SKIP_DIRS:
                return True
        return False

    def collect_java_files(self) -> List[JavaFile]:
        """Collect all .java files, respecting skip dirs and max_files cap."""
        java_files: List[JavaFile] = []

        # Prioritise src/main over src/test (include test if budget allows)
        all_java = list(self.repo_root.rglob("*.java"))

        # Sort: main sources first, then test
        def priority(p: Path) -> int:
            s = str(p)
            if "/src/main/" in s:
                return 0
            if "/src/test/" in s:
                return 2
            return 1

        all_java.sort(key=priority)

        for java_path in all_java:
            if len(java_files) >= self.max_files:
                break
            if self._should_skip_dir(java_path.relative_to(self.repo_root)):
                continue
            try:
                content = java_path.read_text(encoding="utf-8", errors="replace")
                sha = self._sha256(content)
                rel = str(java_path.relative_to(self.repo_root))

                java_files.append(JavaFile(
                    path=java_path,
                    relative_path=rel,
                    content=content,
                    sha256=sha,
                    size_bytes=java_path.stat().st_size,
                    package=self._extract_package(content),
                ))
                self.cache[rel] = sha
            except Exception:
                continue

        self._save_cache()
        return java_files

    def collect_infra_files(self) -> List[InfraFile]:
        """Collect Dockerfiles, pom.xml, k8s YAMLs, Terraform, GH Actions, properties."""
        infra_files: List[InfraFile] = []
        seen = set()

        def add(path: Path, category: str):
            rel = str(path.relative_to(self.repo_root))
            if rel in seen or not path.exists():
                return
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                # Limit large infra files
                if len(content) > 50_000:
                    content = content[:50_000] + "\n... (truncated)"
                seen.add(rel)
                infra_files.append(InfraFile(
                    path=path, relative_path=rel, content=content, category=category
                ))
            except Exception:
                pass

        # Walk repo for infra files
        for file_path in self.repo_root.rglob("*"):
            if not file_path.is_file():
                continue
            if self._should_skip_dir(file_path.relative_to(self.repo_root)):
                continue

            name = file_path.name
            rel_str = str(file_path.relative_to(self.repo_root))

            if name in ("Dockerfile",) or name.startswith("Dockerfile."):
                add(file_path, "dockerfile")
            elif name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
                add(file_path, "docker_compose")
            elif name in ("pom.xml",):
                add(file_path, "maven")
            elif name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
                add(file_path, "gradle")
            elif name.endswith(".tf") or name.endswith(".tfvars"):
                add(file_path, "terraform")
            elif ".github/workflows" in rel_str and name.endswith((".yml", ".yaml")):
                add(file_path, "github_actions")
            elif name in ("application.properties", "application.yml", "application.yaml") or \
                 name.startswith("application-"):
                add(file_path, "spring_properties")
            elif name.endswith((".yml", ".yaml")):
                # Detect kubernetes by content keywords
                try:
                    txt = file_path.read_text(encoding="utf-8", errors="replace")
                    if any(k in txt for k in ("apiVersion:", "kind: Deployment", "kind: Service", "kind: Pod")):
                        add(file_path, "kubernetes")
                except Exception:
                    pass

        return infra_files

    def collect_python_files(self, max_files: int = 150) -> List[PythonFile]:
        """Collect .py files, skipping __pycache__, migrations, venv."""
        SKIP_PY_DIRS = SKIP_DIRS | {"migrations", "venv", ".venv", "env", "site-packages"}
        py_files: List[PythonFile] = []

        def priority(p: Path) -> int:
            s = str(p)
            if "test" in s.lower():
                return 2
            if "__init__" in s:
                return 1
            return 0

        all_py = sorted(self.repo_root.rglob("*.py"), key=priority)

        for py_path in all_py:
            if len(py_files) >= max_files:
                break
            rel = py_path.relative_to(self.repo_root)
            if any(part in SKIP_PY_DIRS for part in rel.parts):
                continue
            try:
                content = py_path.read_text(encoding="utf-8", errors="replace")
                sha = self._sha256(content)
                py_files.append(PythonFile(
                    path=py_path,
                    relative_path=str(rel),
                    content=content,
                    sha256=sha,
                    size_bytes=py_path.stat().st_size,
                ))
            except Exception:
                continue
        return py_files

    def collect_ts_files(self, max_files: int = 150) -> List[TypeScriptFile]:
        """Collect .ts/.tsx files, skipping node_modules, dist, .spec files optionally."""
        SKIP_TS_DIRS = SKIP_DIRS | {".angular", ".cache"}
        ts_files: List[TypeScriptFile] = []

        def priority(p: Path) -> int:
            s = str(p)
            if ".spec." in s or ".test." in s:
                return 3
            if "node_modules" in s:
                return 4
            if ".module." in s or ".component." in s or ".service." in s:
                return 0
            return 1

        all_ts = sorted(
            list(self.repo_root.rglob("*.ts")) + list(self.repo_root.rglob("*.tsx")),
            key=priority
        )

        for ts_path in all_ts:
            if len(ts_files) >= max_files:
                break
            rel = ts_path.relative_to(self.repo_root)
            if any(part in SKIP_TS_DIRS for part in rel.parts):
                continue
            # Skip .d.ts declaration files
            if ts_path.name.endswith(".d.ts"):
                continue
            try:
                content = ts_path.read_text(encoding="utf-8", errors="replace")
                sha = self._sha256(content)
                ts_files.append(TypeScriptFile(
                    path=ts_path,
                    relative_path=str(rel),
                    content=content,
                    sha256=sha,
                    size_bytes=ts_path.stat().st_size,
                    file_type=ts_path.suffix,
                ))
            except Exception:
                continue
        return ts_files

    def detect_languages(self) -> List[str]:
        """Quick scan to detect which languages are present in the repo."""
        langs = []
        if any(self.repo_root.rglob("*.java")):
            langs.append("java")
        if any(self.repo_root.rglob("*.py")):
            langs.append("python")
        if any(self.repo_root.rglob("*.ts")):
            langs.append("typescript")
            # Detect Angular specifically
            if any(self.repo_root.rglob("angular.json")) or \
               any(self.repo_root.rglob(".angular")):
                langs.append("angular")
        return langs

    def _extract_package(self, content: str) -> Optional[str]:
        """Quick regex-free package extraction from Java source."""
        for line in content.splitlines()[:10]:
            stripped = line.strip()
            if stripped.startswith("package ") and stripped.endswith(";"):
                return stripped[8:-1].strip()
        return None
