"""Markdown generation. Pass-through with optional YAML frontmatter."""
from pathlib import Path
from typing import Any, Dict
import re


def _slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[\s_-]+", "-", s).strip("-")


def render(
    title: str,
    content: str,
    output_path: Path,
    metadata: Dict[str, Any] = None,
) -> Path:
    metadata = metadata or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frontmatter_lines = ["---"]
    frontmatter_lines.append(f"title: {title}")
    if metadata.get("author"):
        frontmatter_lines.append(f"author: {metadata['author']}")
    if metadata.get("date"):
        frontmatter_lines.append(f"date: {metadata['date']}")
    if metadata.get("tags"):
        frontmatter_lines.append(f"tags: [{', '.join(metadata['tags'])}]")
    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    out = "\n".join(frontmatter_lines) + content
    output_path.write_text(out, encoding="utf-8")
    return output_path
