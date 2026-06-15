"""
Documents Plugin API.

Endpoints (mounted by web_server at /api/plugins/documents/...):
  GET  /health
  GET  /templates
  POST /generate
  GET  /
  GET  /{doc_id}
  GET  /{doc_id}/download
  GET  /{doc_id}/preview
  POST /search
  POST /index

This module is importable in two contexts:
  1. As a package member: `from documents.plugin_api import router` (relative imports OK)
  2. As a standalone file via importlib.util.spec_from_file_location (web_server
     auto-mount): relative imports break. In that case we bootstrap sys.path
     to make the submodules importable as top-level names.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Bootstrap imports for both contexts ────────────────────────────
_HERE = Path(__file__).resolve().parent
_PLUGIN_DIR = _HERE  # /plugins/documents
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:
    # Package context: `from documents.generators import generate`
    from .generators import generate as _generate_doc
    from .rag.chunker import chunk_markdown, chunk_plain
    from .rag.store import RagStore
except ImportError:
    # File-loaded context: import as top-level modules
    from generators import generate as _generate_doc
    from rag.chunker import chunk_markdown, chunk_plain
    from rag.store import RagStore

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field


router = APIRouter(tags=["documents"])

# ── Config ──────────────────────────────────────────────────────────
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("DOCUMENTS_EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("DOCUMENTS_COLLECTION", "documents_chunks")

DOCS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(Path.home() / ".hermes" / "documents")))
OUTPUT_DIR = DOCS_DIR / "output"
INDEX_DIR = DOCS_DIR / "index"
for d in (DOCS_DIR, OUTPUT_DIR, INDEX_DIR):
    d.mkdir(parents=True, exist_ok=True)

_store: Optional[RagStore] = None


def get_store() -> RagStore:
    global _store
    if _store is None:
        _store = RagStore(
            qdrant_url=QDRANT_URL,
            ollama_url=OLLAMA_URL,
            embed_model=EMBED_MODEL,
            collection=COLLECTION,
        )
    return _store


# ── Models ──────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    format: str = Field(..., description="html | pdf | docx | md | csv | xlsx")
    title: str
    content: str = Field(..., description="Markdown or HTML source")
    template: Optional[str] = "default"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_doc_ids: Optional[List[str]] = Field(default=None, description="Library doc IDs to cite")


class GenerateResponse(BaseModel):
    id: str
    format: str
    title: str
    path: str
    size: int
    created_at: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class IndexRequest(BaseModel):
    source_path: str
    content: str
    folder: str = "default"
    tags: List[str] = Field(default_factory=list)
    title: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    folder: Optional[str] = None
    with_citations: bool = True


# ── Helpers ─────────────────────────────────────────────────────────
def _meta_path(doc_id: str) -> Path:
    return INDEX_DIR / f"{doc_id}.json"


def _load_meta(doc_id: str) -> Optional[Dict[str, Any]]:
    p = _meta_path(doc_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _save_meta(meta: Dict[str, Any]) -> None:
    p = _meta_path(meta["id"])
    p.write_text(json.dumps(meta, indent=2, ensure_ascii=False))


# ── Routes ──────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    info: Dict[str, Any] = {
        "status": "ok",
        "plugin": "documents",
        "time": datetime.utcnow().isoformat(),
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=5.0)
            info["qdrant"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as e:
        info["qdrant"] = f"err: {e}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": "ping"},
                timeout=10.0,
            )
            info["embed"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as e:
        info["embed"] = f"err: {e}"
    return info


@router.get("/templates")
async def list_templates():
    from generators.html_gen import list_templates as _list
    return {"templates": _list()}


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    fmt = req.format.lower()
    if fmt not in ("html", "pdf", "docx", "md", "csv", "xlsx"):
        raise HTTPException(400, f"unsupported format: {fmt}")

    doc_id = uuid.uuid4().hex[:12]
    out_path = OUTPUT_DIR / f"{doc_id}.{fmt}"

    try:
        _generate_doc(
            fmt=fmt,
            title=req.title,
            content=req.content,
            output_path=out_path,
            template=req.template or "default",
            metadata=req.metadata,
        )
    except Exception as e:
        raise HTTPException(500, f"generation failed: {e}")

    citations: List[Dict[str, Any]] = []
    if req.source_doc_ids:
        for sid in req.source_doc_ids:
            meta = _load_meta(sid)
            if meta:
                citations.append(
                    {"doc_id": sid, "title": meta.get("title"), "path": meta.get("source_path")}
                )

    meta = {
        "id": doc_id,
        "title": req.title,
        "format": fmt,
        "path": str(out_path),
        "size": out_path.stat().st_size,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "metadata": req.metadata,
        "template": req.template,
        "citations": citations,
    }
    _save_meta(meta)
    return GenerateResponse(**meta)


@router.get("")
async def list_docs(
    limit: int = Query(50, ge=1, le=500),
    format: Optional[str] = None,
):
    items: List[Dict[str, Any]] = []
    for p in sorted(INDEX_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            m = json.loads(p.read_text())
            if format and m.get("format") != format:
                continue
            items.append(
                {
                    "id": m["id"],
                    "title": m["title"],
                    "format": m["format"],
                    "size": m["size"],
                    "created_at": m["created_at"],
                }
            )
        except Exception:
            continue
        if len(items) >= limit:
            break
    return {"docs": items, "total": len(items)}


@router.get("/{doc_id}")
async def get_doc(doc_id: str):
    meta = _load_meta(doc_id)
    if not meta:
        raise HTTPException(404, "doc not found")
    return meta


@router.get("/{doc_id}/download")
async def download_doc(doc_id: str):
    meta = _load_meta(doc_id)
    if not meta:
        raise HTTPException(404, "doc not found")
    p = Path(meta["path"])
    if not p.exists():
        raise HTTPException(404, "file missing on disk")
    media = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html": "text/html",
        "md": "text/markdown",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(meta["format"], "application/octet-stream")
    return FileResponse(p, media_type=media, filename=p.name)


@router.get("/{doc_id}/preview")
async def preview_doc(doc_id: str):
    meta = _load_meta(doc_id)
    if not meta:
        raise HTTPException(404, "doc not found")
    p = Path(meta["path"])
    if not p.exists():
        raise HTTPException(404, "file missing on disk")
    fmt = meta["format"]
    if fmt == "html":
        return FileResponse(p, media_type="text/html")
    if fmt == "md":
        text = p.read_text()
        return JSONResponse({"format": "md", "text": text, "title": meta["title"]})
    if fmt in ("pdf", "docx", "csv", "xlsx"):
        return JSONResponse(
            {
                "format": fmt,
                "url": f"/api/plugins/documents/{doc_id}/download",
                "title": meta["title"],
            }
        )
    raise HTTPException(400, f"no preview for {fmt}")


@router.post("/index")
async def index_doc(req: IndexRequest):
    chunks = chunk_markdown(req.content, source_path=req.source_path)
    if not chunks:
        chunks = chunk_plain(req.content, source_path=req.source_path)

    title = req.title or Path(req.source_path).stem
    store = get_store()
    n = await store.upsert(
        chunks=chunks,
        source_path=req.source_path,
        title=title,
        folder=req.folder,
        tags=req.tags,
    )
    return {"indexed": n, "source_path": req.source_path, "chunks": len(chunks)}


@router.post("/search")
async def search(req: SearchRequest):
    store = get_store()
    hits = await store.search(query=req.query, top_k=req.top_k, folder=req.folder)
    out = []
    for h in hits:
        item = {
            "score": h.get("score"),
            "text": h.get("payload", {}).get("text", ""),
            "source_path": h.get("payload", {}).get("source_path"),
            "title": h.get("payload", {}).get("title"),
            "folder": h.get("payload", {}).get("folder"),
        }
        if req.with_citations:
            item["citation"] = {
                "heading_path": h.get("payload", {}).get("heading_path", []),
                "paragraph_index": h.get("payload", {}).get("paragraph_index"),
                "char_start": h.get("payload", {}).get("char_start"),
                "char_end": h.get("payload", {}).get("char_end"),
            }
        out.append(item)
    return {"hits": out, "query": req.query, "total": len(out)}
