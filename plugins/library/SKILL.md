---
name: library-reader
description: Search and read documents from the Library plugin (second memory layer).
category: memory
toolsets: [web, vision]
---

# Library Reader

Search and retrieve documents from the local Library (document store).
The Library is a second memory layer alongside mem0, storing documents with
semantic search via Qdrant + Ollama embeddings.

## Architecture

- **Text docs** (txt, md, pdf-with-text): indexed, searchable directly.
- **Binary docs** (images, scanned PDFs): stored raw. OCR is done via
  Hermes native `vision_analyze` tool, NOT by the plugin.

## Tools

- `library_search` → semantic search
- `library_get` → fetch document metadata
- `library_get_file` → fetch raw binary (for vision_analyze)
- `vision_analyze` → OCR on image/scanned PDF pages

## API Base

All endpoints under `/api/library`.

## Endpoints

### Search
```
POST /api/library/search
{"query": "how to patch Hermes", "top_k": 5, "folder": "docs"}
```

### Get doc
```
GET /api/library/docs/{doc_id}
```

### Get raw file (binary docs)
```
GET /api/library/docs/{doc_id}/file
```

## Binary Doc OCR Workflow

1. `GET /api/library/docs/{id}` → check `content_type: "binary"` and `tags: ["needs_ocr"]`
2. `GET /api/library/docs/{id}/file` → download the image/PDF
3. Use `vision_analyze` on the file to extract text
4. `PUT /api/library/docs/{id}` with the extracted text in `content`
   → doc becomes text-type, gets indexed

## Constraints

- Read-only via API for routine queries. OCR updates are the ONLY write path.
- Never delete or modify docs unless explicitly asked.
- If no hits, state that Library has no matching docs.
