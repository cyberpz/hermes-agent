"""Document generators dispatch by format."""
from pathlib import Path
from typing import Any, Dict


def generate(
    fmt: str,
    title: str,
    content: str,
    output_path: Path,
    template: str = "default",
    metadata: Dict[str, Any] = None,
) -> Path:
    metadata = metadata or {}
    fmt = fmt.lower()
    if fmt == "html":
        from .html_gen import render
        return render(title, content, output_path, template=template, metadata=metadata)
    if fmt == "pdf":
        from .pdf_gen import render
        return render(title, content, output_path, template=template, metadata=metadata)
    if fmt == "docx":
        from .docx_gen import render
        return render(title, content, output_path, metadata=metadata)
    if fmt == "md":
        from .md_gen import render
        return render(title, content, output_path, metadata=metadata)
    if fmt == "csv":
        from .csv_gen import render
        return render(title, content, output_path, metadata=metadata)
    if fmt == "xlsx":
        from .xlsx_gen import render
        return render(title, content, output_path, metadata=metadata)
    raise ValueError(f"unsupported format: {fmt}")
