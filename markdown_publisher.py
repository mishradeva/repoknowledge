"""
MarkdownPublisher: Writes WikiPage objects to the filesystem.
Creates directories as needed. Returns count of files written.
"""
from pathlib import Path
from typing import List
from generators.wiki_generator import WikiPage


class MarkdownPublisher:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def publish(self, pages: List[WikiPage]) -> int:
        written = 0
        for page in pages:
            dest = self.output_dir / page.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(page.content, encoding="utf-8")
            written += 1
        return written
