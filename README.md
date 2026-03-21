# RepoWiki — Java Edition

Auto-generate DeepWiki-style documentation for Java / Spring Boot repositories.
Produces architecture diagrams, component maps, API references, infra docs, and
dependency graphs — all as Mermaid-powered Markdown files committed into your repo.

## What it generates

```
docs/wiki/
├── index.md              ← overview, tech stack badges, nav
├── architecture.md       ← C4 system diagram + sequence diagram
├── components/
│   ├── user-service.md   ← per-group deep-dives
│   └── order-service.md
├── api-reference.md      ← all @GetMapping / @PostMapping etc.
├── data-models.md        ← JPA entities + ERD
├── infrastructure.md     ← Docker, K8s, CI/CD, env vars
└── dependencies.md       ← class dependency graph
```

## Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)
- GitHub PAT (only needed for `--github-url` mode)

## Installation

```bash
git clone https://github.com/your-org/repowiki
cd repowiki
pip install -r requirements.txt
```

## Usage

### Analyse a local repo

```bash
export ANTHROPIC_API_KEY=sk-ant-...

python cli.py generate \
  --repo /path/to/your/java-project \
  --output docs/wiki
```

### Analyse a remote GitHub repo

```bash
python cli.py generate \
  --github-url https://github.com/your-org/your-service \
  --token ghp_your_pat \
  --output docs/wiki
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--repo` | — | Local path to repo |
| `--github-url` | — | GitHub HTTPS URL |
| `--token` | `$GITHUB_TOKEN` | GitHub PAT for private repos |
| `--output` | `docs/wiki` | Output directory |
| `--max-files` | `100` | Max Java files to analyse |
| `--verbose` | false | Show API call progress |

## CI/CD — Auto-update on every push

Copy `.github/workflows/repowiki.yml` into your target repo and add:

```
Settings → Secrets → Actions:
  ANTHROPIC_API_KEY = sk-ant-...
```

RepoWiki will open a PR updating `docs/wiki/` on every push to `main`.

## How it works

```
1. Crawl        Walk repo, collect .java + infra files, skip build artifacts
2. Parse        javalang AST → extract classes, methods, annotations, endpoints
3. Analyse      Claude API (3-pass):
                  Pass 1 — per-file JSON summaries (parallel)
                  Pass 2 — service group aggregation + infra analysis
                  Pass 3 — system architecture + Mermaid diagram generation
4. Generate     Render 6+ Markdown wiki pages
5. Publish      Write to docs/wiki/, create PR (CI mode)
```

## Cost estimate

| Repo size | Java files | Approx API cost |
|---|---|---|
| Small service | 20–50 | ~$0.05 |
| Medium monolith | 50–150 | ~$0.20 |
| Large monolith | 150–300 | ~$0.50 |

File-hash caching means re-runs only charge for changed files.

## Adding support for other languages

The architecture is extensible. To add Python/TypeScript/Angular support:
1. Add a parser in `parsers/` implementing the same `ParsedFile` interface
2. Extend `RepoCrawler.collect_*_files()`
3. The rest of the pipeline (analyser → generators → publisher) is language-agnostic
