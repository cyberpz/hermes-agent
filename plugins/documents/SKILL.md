---
name: documents
description: Generate documents (PDF, DOCX, HTML, Markdown, CSV, XLSX) and search indexed documents with paragraph-level citations.
category: productivity
toolsets: [web]
---

# Documents Plugin

Document generation + RAG search with paragraph citations.

## When to load

- User asks to create a PDF/DOCX/HTML/MD/CSV/XLSX from content
- User wants to search across previously indexed documents with citations
- User wants a generated report from search results

## Tools (via the plugin API)

All endpoints under `/api/documents` on the Hermes plugin server.

### Generate document

```
POST /api/documents/generate
{
  "format": "pdf" | "docx" | "html" | "md" | "csv" | "xlsx",
  "title": "Q4 Report",
  "content": "# Heading\n\nMarkdown body...",
  "template": "default" | "report" | "briefing",
  "metadata": {"author": "...", "date": "...", "tags": [...]},
  "source_doc_ids": ["abc123", ...]   // optional: cite these sources
}
```

Returns `{id, format, path, size, citations}`.

### List / Get / Download

```
GET /api/documents                      # list all generated docs
GET /api/documents/{id}                 # metadata
GET /api/documents/{id}/download        # file binary
GET /api/documents/{id}/preview         # preview (html for HTML/MD, link for PDF/DOCX)
```

### Search with citations

```
POST /api/documents/search
{
  "query": "patch Hermes",
  "top_k": 5,
  "folder": "docs",     // optional filter
  "with_citations": true
}
```

Returns hits with citation metadata:
```json
{
  "hits": [{
    "score": 0.87,
    "text": "...",
    "source_path": "~/notes/hermes.md",
    "title": "Hermes Patches",
    "citation": {
      "heading_path": ["Cap 2", "Sez 2.3"],
      "paragraph_index": 12,
      "char_start": 4521,
      "char_end": 4893
    }
  }]
}
```

### Index a document for RAG

```
POST /api/documents/index
{
  "source_path": "~/notes/hermes.md",
  "content": "...",
  "folder": "docs",
  "tags": ["guide"],
  "title": "Hermes Patches"
}
```

### Templates

```
GET /api/documents/templates
```

## Workflow: search + generate report

1. `documents_search` with the user's question.
2. For each top hit, read the source paragraph (already in `text`).
3. Compose a Markdown synthesis citing the paragraphs (use `source_path > heading_path > ¶ N`).
4. Call `documents_generate` with `format="pdf"` and `template="report"`.
5. Pass the original `source_doc_ids` to attach citations to the generated doc.

## Constraints

- Generation is **manual trigger** only — no auto-generation from cron/kanban.
- Sources are **local FS only** in this version (no Drive/Notion).
- Paragraph-level citations (heading path + paragraph index). For sub-paragraph precision, point to the `char_start/char_end` span.
- Markdown is the canonical input format. HTML is the rendering intermediate; DOCX/PDF/HTML/MD all derive from the same Markdown source.

## Output formats

| format | engine                | when to use                       |
|--------|-----------------------|-----------------------------------|
| html   | Jinja2                | preview, web display              |
| pdf    | WeasyPrint            | final printable artifact          |
| docx   | python-docx           | Word editing, sharing             |
| md     | passthrough + YAML FM | canonical source, version control |
| csv    | csv stdlib            | tabular data, single sheet        |
| xlsx   | openpyxl              | tabular data, multiple sheets     |

## Companion skill

`library-reader` covers **read-only** search of the Library plugin. `documents` covers **generation** + **indexable search** of arbitrary docs. When the user wants a generated report from library content, chain: `library_search` → `documents_generate`.
