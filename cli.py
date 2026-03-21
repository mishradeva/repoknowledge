#!/usr/bin/env python3
"""
RepoWiki CLI - Generate DeepWiki-style documentation for Java repos
Usage:
    python cli.py generate --repo /path/to/repo --output docs/wiki
    python cli.py generate --github-url https://github.com/org/repo --token ghp_xxx
"""
import typer
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

app = typer.Typer(help="RepoWiki: Auto-generate architecture docs for Java repos")
console = Console()


@app.command()
def generate(
    repo: str = typer.Option(None, "--repo", help="Local path to repo"),
    github_url: str = typer.Option(None, "--github-url", help="GitHub repo URL"),
    token: str = typer.Option(None, "--token", envvar="GITHUB_TOKEN", help="GitHub PAT"),
    output: str = typer.Option("docs/wiki", "--output", help="Output directory for wiki"),
    anthropic_key: str = typer.Option(..., envvar="ANTHROPIC_API_KEY", help="Anthropic API key"),
    max_files: int = typer.Option(100, "--max-files", help="Max Java files to analyse"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Generate a full wiki from a Java repository."""
    from crawler.repo_crawler import RepoCrawler
    from parsers.java_parser import JavaParser
    from analyzer.claude_client import ClaudeAnalyzer
    from generators.wiki_generator import WikiGenerator
    from publishers.markdown_publisher import MarkdownPublisher

    console.print(Panel.fit("🏗  RepoWiki — Java Edition", style="bold blue"))

    # Resolve repo path
    if repo:
        repo_path = Path(repo).resolve()
        if not repo_path.exists():
            console.print(f"[red]Error: repo path {repo_path} does not exist[/red]")
            raise typer.Exit(1)
        repo_name = repo_path.name
    elif github_url:
        console.print(f"[yellow]Cloning {github_url}...[/yellow]")
        from crawler.github_fetcher import clone_repo
        repo_path = clone_repo(github_url, token)
        repo_name = github_url.rstrip("/").split("/")[-1]
    else:
        console.print("[red]Provide --repo or --github-url[/red]")
        raise typer.Exit(1)

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:

        # Step 1: Crawl
        task = progress.add_task("Crawling repository...", total=None)
        crawler = RepoCrawler(repo_path, max_files=max_files)
        files = crawler.collect_java_files()
        infra_files = crawler.collect_infra_files()
        progress.update(task, description=f"Found {len(files)} Java files, {len(infra_files)} infra files")
        progress.stop_task(task)

        # Step 2: Parse
        task = progress.add_task("Parsing Java AST...", total=None)
        parser = JavaParser(verbose=verbose)
        parsed_modules = parser.parse_files(files)
        progress.update(task, description=f"Parsed {len(parsed_modules)} modules")
        progress.stop_task(task)

        # Step 3: Analyse with Claude
        task = progress.add_task("Analysing with Claude...", total=None)
        analyzer = ClaudeAnalyzer(api_key=anthropic_key, verbose=verbose)
        analysis = analyzer.analyse(parsed_modules, infra_files, repo_name)
        progress.update(task, description="Analysis complete")
        progress.stop_task(task)

        # Step 4: Generate wiki pages
        task = progress.add_task("Generating wiki pages...", total=None)
        generator = WikiGenerator(analysis, repo_name)
        wiki_pages = generator.generate_all()
        progress.update(task, description=f"Generated {len(wiki_pages)} pages")
        progress.stop_task(task)

        # Step 5: Publish
        task = progress.add_task("Writing markdown files...", total=None)
        publisher = MarkdownPublisher(output_path)
        written = publisher.publish(wiki_pages)
        progress.update(task, description=f"Written {written} files")
        progress.stop_task(task)

    console.print(f"\n[bold green]✓ Wiki generated at: {output_path.resolve()}[/bold green]")
    console.print(f"  • {output_path}/index.md  — start here")
    console.print(f"  • {output_path}/architecture.md")
    console.print(f"  • {output_path}/components/")
    console.print(f"  • {output_path}/infrastructure.md")
    console.print(f"  • {output_path}/api-reference.md")


if __name__ == "__main__":
    app()
