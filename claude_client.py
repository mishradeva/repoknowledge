"""
ClaudeAnalyzer: Sends parsed Java module data to Claude API.
Uses a 3-pass bottom-up strategy:
  Pass 1 — per-file analysis (batched, parallel)
  Pass 2 — service/package level aggregation
  Pass 3 — system-level architecture + diagram generation

All responses are requested as structured JSON.
Includes exponential backoff retry and file-hash-based caching.
"""
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from parsers.java_parser import ParsedJavaFile


MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4096
CACHE_FILE = ".repowiki_analysis_cache.json"


@dataclass
class RepoAnalysis:
    repo_name: str
    system_purpose: str
    tech_stack: List[str]
    architecture_style: str            # monolith / microservices / layered / hexagonal
    modules: List[Dict[str, Any]]      # per-module summaries
    services: List[Dict[str, Any]]     # grouped by role
    dependencies: Dict[str, List[str]] # class -> [injected types]
    endpoints: List[Dict[str, str]]    # all HTTP endpoints
    infra_summary: Dict[str, Any]      # docker, k8s, terraform, CI/CD
    mermaid_architecture: str          # C4-style system diagram
    mermaid_components: str            # component/dependency diagram
    mermaid_sequence: str              # key data flow sequence diagram
    data_models: List[Dict[str, Any]]  # JPA entities
    key_packages: List[str]


class ClaudeAnalyzer:
    def __init__(self, api_key: str, verbose: bool = False):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.verbose = verbose
        self.cache: Dict[str, Any] = {}

    def analyse(
        self,
        parsed_modules: List[ParsedJavaFile],
        infra_files: list,
        repo_name: str,
    ) -> RepoAnalysis:

        if self.verbose:
            print(f"  Analysing {len(parsed_modules)} modules in 3 passes...")

        # Pass 1: per-file summaries (batch, up to 10 parallel)
        module_summaries = self._pass1_module_summaries(parsed_modules)

        # Pass 2: service grouping + infra
        service_groups, infra_summary = self._pass2_service_level(
            module_summaries, infra_files, repo_name
        )

        # Pass 3: system architecture + diagrams
        system = self._pass3_system_level(
            module_summaries, service_groups, infra_summary, repo_name
        )

        # Collect all endpoints
        all_endpoints = []
        for m in parsed_modules:
            for ep in m.endpoints:
                all_endpoints.append({**ep, "class": m.class_name or ""})

        # Collect data models
        data_models = [
            {"class": m.class_name, "package": m.package, "fields": [
                {"name": f.name, "type": f.type} for f in m.fields
            ]}
            for m in parsed_modules
            if "entity" in m.role.lower() or "model" in m.role.lower()
        ]

        # Build dependency map
        dep_map = {
            m.class_name: m.dependencies
            for m in parsed_modules
            if m.class_name and m.dependencies
        }

        return RepoAnalysis(
            repo_name=repo_name,
            system_purpose=system.get("system_purpose", ""),
            tech_stack=system.get("tech_stack", []),
            architecture_style=system.get("architecture_style", "layered"),
            modules=module_summaries,
            services=service_groups,
            dependencies=dep_map,
            endpoints=all_endpoints,
            infra_summary=infra_summary,
            mermaid_architecture=system.get("mermaid_architecture", ""),
            mermaid_components=system.get("mermaid_components", ""),
            mermaid_sequence=system.get("mermaid_sequence", ""),
            data_models=data_models,
            key_packages=system.get("key_packages", []),
        )

    # ------------------------------------------------------------------ #
    #  Pass 1: per-file module summaries                                   #
    # ------------------------------------------------------------------ #
    def _pass1_module_summaries(self, modules: List[ParsedJavaFile]) -> List[Dict]:
        summaries = []

        def analyse_one(m: ParsedJavaFile) -> Dict:
            cache_key = hashlib.md5(
                (m.relative_path + m.raw_snippet).encode()
            ).hexdigest()
            if cache_key in self.cache:
                return self.cache[cache_key]

            prompt = self._build_module_prompt(m)
            result = self._call_claude(
                system=MODULE_SYSTEM_PROMPT,
                user=prompt,
                label=f"module:{m.class_name}",
            )
            result["_path"] = m.relative_path
            result["_class"] = m.class_name
            result["_role"] = m.role
            self.cache[cache_key] = result
            return result

        # Up to 5 parallel threads
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(analyse_one, m): m for m in modules}
            for future in as_completed(futures):
                try:
                    summaries.append(future.result())
                except Exception as e:
                    m = futures[future]
                    summaries.append({
                        "_path": m.relative_path,
                        "_class": m.class_name,
                        "_role": m.role,
                        "purpose": "Parse error — skipped",
                        "responsibilities": [],
                        "dependencies": m.dependencies,
                        "endpoints": [asdict(ep) if hasattr(ep, '__dataclass_fields__') else ep
                                      for ep in m.endpoints],
                    })

        return summaries

    def _build_module_prompt(self, m: ParsedJavaFile) -> str:
        methods_txt = "\n".join(
            f"  - {meth.visibility} {meth.return_type} {meth.name}({', '.join(meth.parameters[:3])})"
            + (f" [{', '.join(f'@{a}' for a in meth.annotations[:2])}]" if meth.annotations else "")
            for meth in m.methods[:20]
        )
        fields_txt = "\n".join(
            f"  - {f.type} {f.name}" + (f" [@{', @'.join(f.annotations[:2])}]" if f.annotations else "")
            for f in m.fields[:15]
        )
        endpoints_txt = "\n".join(
            f"  - {ep['method']} {ep['path']} -> {ep['handler']}"
            for ep in m.endpoints
        ) or "  (none)"

        return f"""Analyse this Java class and return JSON.

FILE: {m.relative_path}
PACKAGE: {m.package or 'unknown'}
CLASS: {m.class_type} {m.class_name}
ROLE (inferred): {m.role}
ANNOTATIONS: {', '.join(f'@{a}' for a in m.annotations) or 'none'}
EXTENDS: {m.extends or 'none'}
IMPLEMENTS: {', '.join(m.implements) or 'none'}
DEPENDENCIES (injected): {', '.join(m.dependencies) or 'none'}

METHODS ({len(m.methods)} total, showing first 20):
{methods_txt or '  (none)'}

FIELDS ({len(m.fields)} total):
{fields_txt or '  (none)'}

HTTP ENDPOINTS:
{endpoints_txt}

SOURCE SNIPPET (first 60 lines):
```java
{m.raw_snippet}
```"""

    # ------------------------------------------------------------------ #
    #  Pass 2: service-level grouping + infra                             #
    # ------------------------------------------------------------------ #
    def _pass2_service_level(
        self, module_summaries: List[Dict], infra_files: list, repo_name: str
    ) -> tuple:
        infra_txt = "\n\n".join(
            f"=== {f.category.upper()}: {f.relative_path} ===\n{f.content[:3000]}"
            for f in infra_files[:10]
        ) or "No infra files found."

        # Summarise modules compactly
        modules_txt = json.dumps([
            {k: v for k, v in m.items() if not k.startswith("_") or k in ("_class", "_role", "_path")}
            for m in module_summaries
        ], indent=2)[:12000]  # stay within context

        prompt = f"""You are analysing a Java application called '{repo_name}'.

MODULE SUMMARIES:
{modules_txt}

INFRASTRUCTURE FILES:
{infra_txt}

Return JSON with two keys: "service_groups" and "infra_summary".
"""
        result = self._call_claude(
            system=SERVICE_SYSTEM_PROMPT,
            user=prompt,
            label="pass2:service-level",
            max_tokens=6000,
        )
        return result.get("service_groups", []), result.get("infra_summary", {})

    # ------------------------------------------------------------------ #
    #  Pass 3: system architecture + Mermaid diagrams                     #
    # ------------------------------------------------------------------ #
    def _pass3_system_level(
        self,
        module_summaries: List[Dict],
        service_groups: List[Dict],
        infra_summary: Dict,
        repo_name: str,
    ) -> Dict:
        services_txt = json.dumps(service_groups, indent=2)[:6000]
        infra_txt = json.dumps(infra_summary, indent=2)[:3000]

        prompt = f"""You are creating architecture documentation for '{repo_name}'.

SERVICE GROUPS:
{services_txt}

INFRA SUMMARY:
{infra_txt}

Return JSON with these keys:
- system_purpose (string)
- tech_stack (list of strings)
- architecture_style (string: monolith|microservices|layered|hexagonal)
- key_packages (list of strings)
- mermaid_architecture (valid Mermaid C4Context or graph TD diagram — no backticks)
- mermaid_components (valid Mermaid graph LR component diagram — no backticks)
- mermaid_sequence (valid Mermaid sequenceDiagram for the primary use case — no backticks)
"""
        return self._call_claude(
            system=SYSTEM_ARCH_PROMPT,
            user=prompt,
            label="pass3:system-arch",
            max_tokens=MAX_TOKENS,
        )

    # ------------------------------------------------------------------ #
    #  Claude API call with retry + JSON parse                            #
    # ------------------------------------------------------------------ #
    def _call_claude(
        self,
        system: str,
        user: str,
        label: str = "",
        max_tokens: int = MAX_TOKENS,
        retries: int = 3,
    ) -> Dict[str, Any]:
        for attempt in range(retries):
            try:
                if self.verbose:
                    print(f"    → Claude call: {label} (attempt {attempt+1})")

                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                raw = response.content[0].text.strip()

                # Strip markdown code fences if Claude wrapped in ```json
                if raw.startswith("```"):
                    raw = re.sub(r"^```(?:json)?\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw)

                return json.loads(raw)

            except (json.JSONDecodeError, anthropic.APIError) as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    if self.verbose:
                        print(f"    ⚠ Retry {attempt+1}/{retries} for {label}: {e} (wait {wait}s)")
                    time.sleep(wait)
                else:
                    if self.verbose:
                        print(f"    ✗ Failed {label}: {e}")
                    return {"error": str(e), "purpose": f"Analysis failed: {e}",
                            "responsibilities": [], "dependencies": []}
        return {}


import re  # needed for strip of backticks above


# ------------------------------------------------------------------ #
#  System prompts                                                      #
# ------------------------------------------------------------------ #

MODULE_SYSTEM_PROMPT = """You are a senior Java architect analysing source code.
Return ONLY valid JSON — no prose, no markdown fences.
Schema:
{
  "purpose": "one sentence describing what this class does",
  "responsibilities": ["list", "of", "key", "responsibilities"],
  "dependencies": ["list of classes/services this depends on"],
  "endpoints": [{"method": "GET", "path": "/api/v1/users", "handler": "getUsers", "description": "..."}],
  "data_access": ["JPA repositories or DB interactions mentioned"],
  "events": ["events published or consumed"],
  "notable_patterns": ["design patterns or Spring patterns observed"],
  "complexity": "low|medium|high"
}
If a field is not applicable return an empty list or empty string."""

SERVICE_SYSTEM_PROMPT = """You are a senior Java architect. Analyse these module summaries and infra files.
Return ONLY valid JSON — no prose, no markdown fences.
Schema:
{
  "service_groups": [
    {
      "name": "group name (e.g. User Management, Order Processing)",
      "layer": "presentation|business|data|infrastructure",
      "classes": ["ClassName1", "ClassName2"],
      "purpose": "what this group does",
      "external_dependencies": ["external systems or DBs it talks to"],
      "key_apis": ["primary API endpoints exposed"]
    }
  ],
  "infra_summary": {
    "containerized": true,
    "orchestration": "docker-compose|kubernetes|none",
    "databases": ["list of databases detected"],
    "message_brokers": ["kafka|rabbitmq|none"],
    "cloud_provider": "aws|gcp|azure|none|unknown",
    "ci_cd": "github_actions|jenkins|gitlab_ci|none|unknown",
    "exposed_ports": ["list of ports"],
    "environment_variables": ["key env vars referenced"],
    "services": [{"name": "service name", "image": "docker image", "purpose": "..."}]
  }
}"""

SYSTEM_ARCH_PROMPT = """You are a senior Java architect generating documentation.
Return ONLY valid JSON — no prose, no markdown fences, no backticks inside Mermaid strings.
The Mermaid diagrams must be syntactically valid (no special characters in node IDs, use quotes for labels with spaces).
For mermaid_architecture use: graph TD or C4Context syntax.
For mermaid_components use: graph LR with subgraphs per layer.
For mermaid_sequence use: sequenceDiagram for the main request flow."""
