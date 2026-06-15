# 📚 Hermes Library Plugin

Second-layer memory for documents. Semantic search via Qdrant + Ollama.

## Stack
- Files stored in `~/.hermes/library/`
- Chunks indexed in Qdrant collection `library_docs`
- Embeddings via Ollama `nomic-embed-text`
- Dashboard: vanilla JS, dark theme

## API
- `POST /library/docs` — create
- `GET /library/docs` — list (filter by folder/tag)
- `GET /library/docs/{id}` — read
- `PUT /library/docs/{id}` — update
- `DELETE /library/docs/{id}` — delete
- `POST /library/search` — semantic search
- `GET /library/folders` — list folders

## Skill
`library-reader` — read-only search/fetch for agents.
