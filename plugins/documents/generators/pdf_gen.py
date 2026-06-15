"""PDF generation via WeasyPrint (HTML→PDF)."""
from pathlib import Path
from typing import Any, Dict

from .html_gen import render as render_html


def render(
    title: str,
    content: str,
    output_path: Path,
    template: str = "default",
    metadata: Dict[str, Any] = None,
) -> Path:
    metadata = metadata or {}
    html_path = output_path.with_suffix(".html")
    render_html(title, content, html_path, template=template, metadata=metadata)

    try:
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError(
            "weasyprint not installed. Install with: pip install weasyprint"
        ) from e

    HTML(string=html_path.read_text(encoding="utf-8"), base_url=str(html_path.parent)).write_pdf(
        str(output_path)
    )
    try:
        html_path.unlink()
    except Exception:
        pass
    return output_path
