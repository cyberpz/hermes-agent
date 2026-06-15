# Documents Plugin

Generate documents (PDF, DOCX, HTML, Markdown, CSV, XLSX) and run RAG search with paragraph-level citations.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/api/documents/health` | Status check (Qdrant + Ollama) |
| GET    | `/api/documents/templates` | List HTML templates |
| POST   | `/api/documents/generate` | Generate a document |
| GET    | `/api/documents` | List generated documents |
| GET    | `/api/documents/{id}` | Get document metadata |
| GET    | `/api/documents/{id}/download` | Download file |
| GET    | `/api/documents/{id}/preview` | Preview (HTML inline / link) |
| POST   | `/api/documents/search` | RAG search with paragraph citations |
| POST   | `/api/documents/index` | Index a document for RAG |

## Configuration (env vars)

| Var | Default |
|-----|---------|
| `DOCUMENTS_DIR` | `~/.hermes/documents` |
| `DOCUMENTS_COLLECTION` | `documents_chunks` |
| `DOCUMENTS_EMBED_MODEL` | `nomic-embed-text` |
| `OLLAMA_URL` | `http://localhost:11434` |
| `QDRANT_URL` | `http://localhost:6333` |

## Output formats

| format | engine |
|--------|--------|
| html   | Jinja2 + Markdown |
| pdf    | WeasyPrint (HTML→PDF) |
| docx   | python-docx |
| md     | passthrough + YAML frontmatter |
| csv    | csv stdlib |
| xlsx   | openpyxl |

## Templates

- `default` — clean modern look, blue accent
- `report` — Georgia serif, formal report layout
- `briefing` — card-style morning briefing

## Citation model

Each indexed chunk carries:

- `heading_path` — e.g. `["Cap 2", "Sez 2.3"]`
- `paragraph_index` — sequential integer in source
- `char_start` / `char_end` — span in source text
- `source_path` — absolute file path

Search results include all of the above so you can render citations like:

```
~/notes/hermes.md > Cap 2 > Sez 2.3 > ¶ 12
```

## Layout

```
plugins/documents/
├── plugin.py
├── plugin_api.py
├── plugin.yaml
├── SKILL.md
├── README.md
├── generators/
│   ├── __init__.py
│   ├── html_gen.py
│   ├── pdf_gen.py
│   ├── docx_gen.py
│   ├── md_gen.py
│   ├── csv_gen.py
│   └── xlsx_gen.py
├── rag/
│   ├── __init__.py
│   ├── chunker.py
│   └── store.py
├── templates/
│   ├── default.html.j2
│   ├── report.html.j2
│   └── briefing.html.j2
└── dashboard/        # (TODO: web UI)
```

## Storage

- Generated files: `~/.hermes/documents/output/{id}.{ext}`
- Index metadata: `~/.hermes/documents/index/{id}.json`
- Vector store: Qdrant collection `documents_chunks`
