#!/usr/bin/env python3
"""
RepoWiki CLI — Polyglot edition
Supports: Java · Python · TypeScript · Angular
Output:   Markdown files (default) · Interactive HTML SPA · Both

Usage:
    python cli.py generate --repo /path/to/repo
    python cli.py generate --repo . --format html --output docs/wiki
    python cli.py generate --github-url https://github.com/org/repo --token ghp_xxx
    python cli.py detect --repo .          # just detect languages, no analysis
"""
import typer
import sys
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

app = typer.Typer(help="RepoWiki: Auto-generate architecture docs for any repo")
console = Console()


@app.command()
def generate(
    repo: Optional[str] = typer.Option(None, "--repo", help="Local path to repo"),
    github_url: Optional[str] = typer.Option(None, "--github-url", help="GitHub repo URL"),
    token: Optional[str] = typer.Option(None, "--token", envvar="GITHUB_TOKEN"),
    output: str = typer.Option("docs/wiki", "--output", help="Output directory"),
    fmt: str = typer.Option("both", "--format", "-f",
                             help="Output format: markdown | html | both"),
    anthropic_key: str = typer.Option(..., envvar="ANTHROPIC_API_KEY"),
    max_files: int = typer.Option(100, "--max-files", help="Max source files per language"),
    languages: Optional[str] = typer.Option(None, "--languages",
                                             help="Comma-separated: java,python,typescript,angular"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    skip_tests: bool = typer.Option(True, "--skip-tests/--include-tests"),
):
    """Generate a full wiki from a polyglot repository."""
    from crawler.repo_crawler import RepoCrawler
    from parsers.java_parser import JavaParser
    from parsers.python_parser import PythonParser
    from parsers.ts_angular_parser import TypeScriptAngularParser
    from analyzer.claude_client import ClaudeAnalyzer
    from generators.wiki_generator import WikiGenerator
    from publishers.markdown_publisher import MarkdownPublisher
    from publishers.html_publisher import HTMLPublisher

    console.print(Panel.fit("🏗  RepoWiki — Polyglot Edition", style="bold blue"))

    # Resolve repo path
    if repo:
        repo_path = Path(repo).resolve()
        if not repo_path.exists():
            console.print(f"[red]Error: {repo_path} does not exist[/red]")
            raise typer.Exit(1)
        repo_name = repo_path.name
    elif github_url:
        console.print(f"[yellow]Cloning {github_url}...[/yellow]")
        from crawler.github_fetcher import clone_repo
        repo_path = clone_repo(github_url, token)
        repo_name = github_url.rstrip("/").split("/")[-1].replace(".git", "")
    else:
        console.print("[red]Provide --repo or --github-url[/red]")
        raise typer.Exit(1)

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:

        # Step 1: Crawl
        task = progress.add_task("Scanning repository...", total=None)
        crawler = RepoCrawler(repo_path, max_files=max_files)
        infra_files = crawler.collect_infra_files()
        if languages:
            detected = [l.strip().lower() for l in languages.split(",")]
        else:
            detected = crawler.detect_languages()
        progress.update(task, description=f"Languages detected: {', '.join(detected) or 'none'}")
        progress.stop_task(task)

        # Step 2: Parse each language
        all_parsed = []
        lang_stats = {}

        if "java" in detected:
            task = progress.add_task("Parsing Java...", total=None)
            java_files = crawler.collect_java_files()
            if skip_tests:
                java_files = [f for f in java_files if "/test/" not in f.relative_path.lower()]
            parsed = JavaParser(verbose=verbose).parse_files(java_files)
            all_parsed.extend(_wrap_java(parsed))
            lang_stats["Java"] = len(parsed)
            progress.stop_task(task)

        if "python" in detected:
            task = progress.add_task("Parsing Python...", total=None)
            py_files = crawler.collect_python_files(max_files=max_files)
            if skip_tests:
                py_files = [f for f in py_files
                            if not f.relative_path.lower().startswith("test")]
            parsed = PythonParser(verbose=verbose).parse_files(py_files)
            all_parsed.extend(_wrap_python(parsed))
            lang_stats["Python"] = len(parsed)
            progress.stop_task(task)

        if "typescript" in detected or "angular" in detected:
            task = progress.add_task("Parsing TypeScript/Angular...", total=None)
            ts_files = crawler.collect_ts_files(max_files=max_files)
            if skip_tests:
                ts_files = [f for f in ts_files
                            if ".spec." not in f.relative_path
                            and ".test." not in f.relative_path]
            parsed = TypeScriptAngularParser(verbose=verbose).parse_files(ts_files)
            all_parsed.extend(_wrap_typescript(parsed))
            lang_stats["TypeScript/Angular"] = len(parsed)
            progress.stop_task(task)

        if not all_parsed:
            console.print("[yellow]No source files found.[/yellow]")
            raise typer.Exit(1)

        _print_parse_summary(lang_stats, console)

        # Step 3: Claude analysis
        task = progress.add_task("Analysing with Claude API...", total=None)
        analyzer = ClaudeAnalyzer(api_key=anthropic_key, verbose=verbose)
        analysis = analyzer.analyse_polyglot(all_parsed, infra_files, repo_name, detected)
        progress.stop_task(task)

        # Step 4: Generate pages
        task = progress.add_task("Generating wiki pages...", total=None)
        pages = WikiGenerator(analysis, repo_name).generate_all()
        progress.stop_task(task)

        # Step 5: Publish
        if fmt in ("markdown", "both"):
            task = progress.add_task("Writing Markdown...", total=None)
            MarkdownPublisher(output_path).publish(pages)
            progress.stop_task(task)

        if fmt in ("html", "both"):
            task = progress.add_task("Building HTML wiki...", total=None)
            html_path = HTMLPublisher(output_path / "html").publish(pages, repo_name)
            progress.stop_task(task)

    console.print()
    console.print(f"[bold green]✓ Done![/bold green]  {len(pages)} pages → {output_path}")
    if fmt in ("html", "both"):
        console.print(f"  Open in browser: {output_path}/html/index.html")


@app.command()
def detect(
    repo: str = typer.Option(".", "--repo", help="Local repo path"),
):
    """Detect languages in a repo without running analysis."""
    from crawler.repo_crawler import RepoCrawler
    repo_path = Path(repo).resolve()
    crawler = RepoCrawler(repo_path)
    langs = crawler.detect_languages()
    console.print(f"Languages detected in [bold]{repo_path.name}[/bold]: {', '.join(langs) or 'none'}")


# ---- Wrapper helpers ----

def _wrap_java(parsed_list) -> list:
    return [{
        "language": "java",
        "_path": p.relative_path,
        "_class": p.class_name,
        "_role": p.role,
        "package": p.package,
        "class_type": p.class_type,
        "annotations": p.annotations,
        "methods": [{"name": m.name, "visibility": m.visibility,
                     "return_type": m.return_type, "params": m.parameters[:4]}
                    for m in p.methods[:15]],
        "fields": [{"name": f.name, "type": f.type} for f in p.fields[:10]],
        "dependencies": p.dependencies,
        "endpoints": p.endpoints,
        "extends": p.extends,
        "implements": p.implements,
        "snippet": p.raw_snippet[:1500],
    } for p in parsed_list]


def _wrap_python(parsed_list) -> list:
    return [{
        "language": "python",
        "_path": p.relative_path,
        "_class": p.module_name,
        "_role": p.role,
        "frameworks": p.frameworks,
        "classes": [{"name": c.name, "bases": c.bases,
                     "methods": [m.name for m in c.methods[:8]]}
                    for c in p.classes[:8]],
        "functions": [{"name": f.name, "args": f.args[:4],
                       "return_type": f.return_type,
                       "is_async": f.is_async,
                       "decorators": f.decorators[:3]}
                      for f in p.functions[:12]],
        "imports": p.imports[:15],
        "endpoints": p.endpoints,
        "docstring": p.docstring,
        "snippet": p.raw_snippet[:1500],
    } for p in parsed_list]


def _wrap_typescript(parsed_list) -> list:
    return [{
        "language": "typescript",
        "_path": p.relative_path,
        "_class": p.classes[0].name if p.classes else p.relative_path.split("/")[-1],
        "_role": p.role,
        "framework": p.framework,
        "file_type": p.file_type,
        "classes": [{"name": c.name,
                     "decorators": [d["name"] for d in c.decorators],
                     "methods": [m.name for m in c.methods[:8]],
                     "implements": c.implements}
                    for c in p.classes[:6]],
        "interfaces": [{"name": i.name, "members": i.members[:8]}
                       for i in p.interfaces[:6]],
        "endpoints": p.endpoints,
        "angular_meta": p.angular_meta,
        "exports": p.exports[:10],
        "snippet": p.raw_snippet[:1500],
    } for p in parsed_list]


def _print_parse_summary(lang_stats: dict, console):
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Language", style="cyan")
    t.add_column("Files", style="green", justify="right")
    for lang, count in lang_stats.items():
        t.add_row(lang, str(count))
    console.print(t)
    console.print()


if __name__ == "__main__":
    app()
