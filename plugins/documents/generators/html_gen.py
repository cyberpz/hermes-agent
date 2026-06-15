"""HTML generation via Jinja2 templates."""
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
import markdown as md_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def list_templates() -> List[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return [p.stem for p in TEMPLATES_DIR.glob("*.html.j2")]


def _md_to_html(content: str) -> str:
    return md_lib.markdown(
        content,
        extensions=["fenced_code", "tables", "toc", "sane_lists", "codehilite"],
    )


def _wrap_html(title: str, body_html: str, metadata: Dict[str, Any]) -> str:
    """Fallback wrapper if no template specified/found."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 800px;
            margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #222; }}
    h1, h2, h3 {{ color: #111; }}
    pre {{ background: #f4f4f4; padding: 1em; overflow-x: auto; border-radius: 4px; }}
    code {{ background: #f4f4f4; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.9em; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5em 0.75em; text-align: left; }}
    th {{ background: #f4f4f4; }}
    blockquote {{ border-left: 3px solid #ccc; margin: 1em 0; padding: 0 1em; color: #555; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  {body_html}
</body>
</html>
"""


def render(
    title: str,
    content: str,
    output_path: Path,
    template: str = "default",
    metadata: Dict[str, Any] = None,
) -> Path:
    metadata = metadata or {}
    body_html = _md_to_html(content)

    tpl_name = f"{template}.html.j2"
    tpl_path = TEMPLATES_DIR / tpl_name
    if tpl_path.exists():
        tpl = _env.get_template(tpl_name)
        html = tpl.render(
            title=title,
            body=body_html,
            metadata=metadata,
            generated_at=datetime.utcnow().isoformat() + "Z",
        )
    else:
        html = _wrap_html(title, body_html, metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
