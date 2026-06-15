"""Paragraph-level chunker with heading-path tracking.

Produces citation-friendly chunks:
  - paragraph_index: sequential index within source
  - heading_path: ["Cap 1", "Sez 1.2", ...]  (current heading stack)
  - char_start, char_end: span in source text
"""
import re
from typing import Dict, List


def chunk_markdown(content: str, source_path: str = "") -> List[Dict]:
    """Split markdown by paragraph and headings. Tracks heading context.

    Returns list of:
      {
        "text": "...",
        "heading_path": [...],
        "paragraph_index": int,
        "char_start": int,
        "char_end": int,
        "source_path": "...",
      }
    """
    lines = content.split("\n")
    chunks: List[Dict] = []
    heading_stack: List[str] = []
    para_buf: List[str] = []
    para_start: int = 0
    cur_offset: int = 0
    para_index: int = 0

    def flush_para():
        nonlocal para_buf, para_start, para_index
        if not para_buf:
            return
        text = " ".join(s.strip() for s in para_buf).strip()
        if not text:
            para_buf = []
            return
        chunks.append(
            {
                "text": text,
                "heading_path": list(heading_stack),
                "paragraph_index": para_index,
                "char_start": para_start,
                "char_end": cur_offset,
                "source_path": source_path,
            }
        )
        para_index += 1
        para_buf = []

    i = 0
    in_code = False
    code_lang = ""
    code_buf: List[str] = []

    def flush_code():
        nonlocal code_buf, code_lang
        if code_buf:
            text = "```" + code_lang + "\n" + "\n".join(code_buf) + "\n```"
            chunks.append(
                {
                    "text": text,
                    "heading_path": list(heading_stack),
                    "paragraph_index": para_index,
                    "char_start": para_start,
                    "char_end": cur_offset,
                    "source_path": source_path,
                    "kind": "code",
                }
            )
            para_index += 1
        code_buf = []
        code_lang = ""

    while i < len(lines):
        line = lines[i]
        line_offset = cur_offset
        cur_offset += len(line) + 1  # +1 for newline

        # Fenced code
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_para()
                in_code = True
                code_lang = line.strip().strip("`").strip()
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        stripped = line.strip()

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            title = m.group(2).strip()
            # Truncate stack to current level
            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(title)
            i += 1
            continue

        # Blank line = paragraph break
        if not stripped:
            flush_para()
            i += 1
            continue

        # Start of new paragraph
        if not para_buf:
            para_start = line_offset
        para_buf.append(line)
        i += 1

    flush_para()
    flush_code()
    return chunks


def chunk_plain(content: str, source_path: str = "", size: int = 512, overlap: int = 64) -> List[Dict]:
    """Fallback chunker for non-markdown text. Fixed-size with overlap."""
    chunks: List[Dict] = []
    start = 0
    idx = 0
    n = len(content)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # try to break on whitespace
            j = end
            while j > start and content[j - 1] not in " \n\t":
                j -= 1
            if j > start:
                end = j
        text = content[start:end].strip()
        if text:
            chunks.append(
                {
                    "text": text,
                    "heading_path": [],
                    "paragraph_index": idx,
                    "char_start": start,
                    "char_end": end,
                    "source_path": source_path,
                }
            )
            idx += 1
        if end == start:
            break
        start = max(end - overlap, start + 1)
    return chunks
