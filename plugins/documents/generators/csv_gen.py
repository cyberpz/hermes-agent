"""CSV generation. Accepts a markdown table OR a list of dicts via metadata['rows']."""
import csv
import re
from pathlib import Path
from typing import Any, Dict, List


def _parse_md_table(content: str) -> List[List[str]]:
    """Extract the FIRST markdown table found in content."""
    lines = content.split("\n")
    table = []
    in_table = False
    for line in lines:
        s = line.strip()
        if s.startswith("|") and "|" in s[1:]:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not in_table:
                in_table = True
                table.append(cells)
            else:
                # Skip separator row |---|---|---|
                if all(set(c) <= set("-: ") for c in cells):
                    continue
                table.append(cells)
        elif in_table:
            break
    return table


def render(
    title: str,
    content: str,
    output_path: Path,
    metadata: Dict[str, Any] = None,
) -> Path:
    metadata = metadata or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: List[List[str]] = []
    if metadata.get("rows") and isinstance(metadata["rows"], list):
        if metadata["rows"] and isinstance(metadata["rows"][0], dict):
            # List of dicts → use keys as header
            keys = list(metadata["rows"][0].keys())
            rows.append(keys)
            for r in metadata["rows"]:
                rows.append([str(r.get(k, "")) for k in keys])
        else:
            rows = [[str(c) for c in r] for r in metadata["rows"]]
    else:
        rows = _parse_md_table(content)
        if not rows:
            # Fallback: each non-empty line becomes a row
            rows = [["line"], *[[l] for l in content.splitlines() if l.strip()]]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)
    return output_path
