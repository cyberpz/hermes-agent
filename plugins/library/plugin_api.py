"""
Library Plugin API - Document storage with semantic search.
Text files: extracted + indexed. Binary files: stored raw, OCR via Hermes vision tools.
"""
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/library", tags=["library"])

# ── Config ──────────────────────────────────────────────────────────
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("LIBRARY_EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("LIBRARY_COLLECTION", "library_docs")
LIBRARY_DIR = Path(os.getenv("LIBRARY_DIR", str(Path.home() / ".hermes" / "library")))
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR = LIBRARY_DIR / "files"
FILES_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 128


# ── Models ──────────────────────────────────────────────────────────
class DocCreate(BaseModel):
    title: str
    content: str
    folder: str = "default"
    tags: List[str] = []


class DocUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    folder: Optional[str] = None
    tags: Optional[List[str]] = None


class SearchQuery(BaseModel):
    query: str
    top_k: int = 5
    folder: Optional[str] = None


class ScrapeRequest(BaseModel):
    url: str
    folder: str = "default"
    tags: List[str] = []


# ── Helpers ─────────────────────────────────────────────────────────
def _doc_path(doc_id: str) -> Path:
    return LIBRARY_DIR / f"{doc_id}.md"


def _meta_path(doc_id: str) -> Path:
    return LIBRARY_DIR / f"{doc_id}.json"


def _file_path(doc_id: str, ext: str) -> Path:
    return FILES_DIR / f"{doc_id}{ext}"


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            while end > start and text[end] not in " \n":
                end -= 1
        chunks.append(text[start:end].strip())
        start = end - overlap if end - overlap > start else end
        if start >= len(text) or end == start:
            break
    return chunks or [text]


async def _get_embedding(text: str) -> List[float]:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["embedding"]


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF if available."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        parts = []
        for page in doc:
            txt = page.get_text()
            if txt.strip():
                parts.append(txt)
        doc.close()
        text = "\n".join(parts)
        if text.strip():
            return text
    except Exception:
        pass
    return ""


def _scrape_url_text(url: str) -> tuple:
    """Returns (title, text). Uses trafilatura if available, else basic httpx."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    }
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url, headers=headers)
        if downloaded:
            result = trafilatura.extract(downloaded, include_comments=False, include_tables=True, url=url)
            if result:
                title = url
                try:
                    from trafilatura.metadata import extract_metadata
                    meta = extract_metadata(downloaded, url=url)
                    if meta and meta.title:
                        title = meta.title
                except Exception:
                    pass
                return title, result
    except Exception:
        pass
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=30.0)
    r.raise_for_status()
    html = r.text
    import re
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = m.group(1).strip() if m else url
    return title, text[:50000]


def _ensure_collection():
    try:
        r = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION}")
        if r.status_code == 200:
            return
    except Exception:
        pass
    try:
        test_r = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": "test"},
            timeout=30.0,
        )
        dim = len(test_r.json()["embedding"])
    except Exception:
        dim = 768
    httpx.put(
        f"{QDRANT_URL}/collections/{COLLECTION}",
        json={"vectors": {"size": dim, "distance": "Cosine"}},
    )


async def _index_doc(doc_id: str, title: str, content: str, folder: str, tags: List[str]):
    _ensure_collection()
    chunks = _chunk_text(content)
    for i, chunk in enumerate(chunks):
        emb = await _get_embedding(chunk)
        point_id = hashlib.sha256(f"{doc_id}:{i}".encode()).hexdigest()
        httpx.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
            json={
                "points": [{
                    "id": point_id,
                    "vector": emb,
                    "payload": {
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "text": chunk,
                        "title": title,
                        "folder": folder,
                        "tags": tags,
                    },
                }]
            },
        )


def _delete_qdrant(doc_id: str):
    httpx.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/delete?wait=true",
        json={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}},
    )


# ── CRUD ────────────────────────────────────────────────────────────
@router.post("/docs")
async def create_doc(body: DocCreate):
    doc_id = hashlib.sha256(f"{body.title}{time.time()}".encode()).hexdigest()[:12]
    now = datetime.utcnow().isoformat()
    meta = {
        "id": doc_id,
        "title": body.title,
        "folder": body.folder,
        "tags": body.tags,
        "created_at": now,
        "updated_at": now,
        "size": len(body.content),
        "content_type": "text",
    }
    _doc_path(doc_id).write_text(body.content, encoding="utf-8")
    _meta_path(doc_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    await _index_doc(doc_id, body.title, body.content, body.folder, body.tags)
    return meta


@router.get("/docs")
def list_docs(
    folder: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
):
    docs = []
    for p in sorted(LIBRARY_DIR.glob("*.json")):
        meta = json.loads(p.read_text())
        if folder and meta.get("folder") != folder:
            continue
        if tag and tag not in meta.get("tags", []):
            continue
        if q and q.lower() not in meta.get("title", "").lower():
            continue
        docs.append(meta)
    return {"docs": docs}


@router.get("/docs/{doc_id}")
def get_doc(doc_id: str):
    meta_p = _meta_path(doc_id)
    if not meta_p.exists():
        raise HTTPException(404, "doc not found")
    meta = json.loads(meta_p.read_text())
    if meta.get("content_type") == "text":
        doc_p = _doc_path(doc_id)
        meta["content"] = doc_p.read_text(encoding="utf-8") if doc_p.exists() else ""
    return meta


@router.put("/docs/{doc_id}")
async def update_doc(doc_id: str, body: DocUpdate):
    meta_p = _meta_path(doc_id)
    if not meta_p.exists():
        raise HTTPException(404, "doc not found")
    meta = json.loads(meta_p.read_text())
    _delete_qdrant(doc_id)

    content = ""
    if meta.get("content_type") == "text":
        content = _doc_path(doc_id).read_text(encoding="utf-8")
    if body.content is not None:
        content = body.content
        _doc_path(doc_id).write_text(content, encoding="utf-8")
        meta["content_type"] = "text"
        meta["size"] = len(content)
    if body.title is not None:
        meta["title"] = body.title
    if body.folder is not None:
        meta["folder"] = body.folder
    if body.tags is not None:
        meta["tags"] = body.tags
    meta["updated_at"] = datetime.utcnow().isoformat()
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if content:
        await _index_doc(doc_id, meta["title"], content, meta["folder"], meta.get("tags", []))
    return meta


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: str):
    meta_p = _meta_path(doc_id)
    if not meta_p.exists():
        raise HTTPException(404, "doc not found")
    meta = json.loads(meta_p.read_text())
    _doc_path(doc_id).unlink(missing_ok=True)
    meta_p.unlink(missing_ok=True)
    _delete_qdrant(doc_id)
    # Delete binary file if present
    if meta.get("file_ext"):
        _file_path(doc_id, meta["file_ext"]).unlink(missing_ok=True)
    return {"ok": True}


# ── Upload (text + binary storage) ─────────────────────────────────
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("default"),
    tags: str = Form(""),
):
    """Upload .txt, .md, .pdf, .png, .jpg.
    Text files: extracted + indexed. Binary: stored raw, flagged for OCR."""
    data = await file.read()
    filename = file.filename or "unnamed"
    base_title = Path(filename).stem
    ext = Path(filename).suffix.lower()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    doc_id = hashlib.sha256(f"{filename}{time.time()}".encode()).hexdigest()[:12]
    now = datetime.utcnow().isoformat()

    if ext in (".txt", ".md"):
        content = data.decode("utf-8", errors="ignore")
        meta = {
            "id": doc_id, "title": base_title, "folder": folder, "tags": tag_list,
            "created_at": now, "updated_at": now, "size": len(content),
            "content_type": "text", "source_file": filename,
        }
        _doc_path(doc_id).write_text(content, encoding="utf-8")
        _meta_path(doc_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        await _index_doc(doc_id, base_title, content, folder, tag_list)
        return meta

    elif ext == ".pdf":
        content = _extract_pdf_text(data)
        if content.strip():
            meta = {
                "id": doc_id, "title": base_title, "folder": folder,
                "tags": tag_list + ["pdf"],
                "created_at": now, "updated_at": now, "size": len(content),
                "content_type": "text", "source_file": filename,
            }
            _doc_path(doc_id).write_text(content, encoding="utf-8")
            _meta_path(doc_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
            await _index_doc(doc_id, base_title, content, folder, meta["tags"])
            return meta
        else:
            # Scanned PDF: store binary, flag for OCR
            meta = {
                "id": doc_id, "title": base_title, "folder": folder,
                "tags": tag_list + ["pdf", "needs_ocr"],
                "created_at": now, "updated_at": now, "size": len(data),
                "content_type": "binary", "file_ext": ext,
                "source_file": filename,
            }
            _file_path(doc_id, ext).write_bytes(data)
            _meta_path(doc_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta

    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        meta = {
            "id": doc_id, "title": base_title, "folder": folder,
            "tags": tag_list + ["image", "needs_ocr"],
            "created_at": now, "updated_at": now, "size": len(data),
            "content_type": "binary", "file_ext": ext,
            "source_file": filename,
        }
        _file_path(doc_id, ext).write_bytes(data)
        _meta_path(doc_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    else:
        raise HTTPException(400, f"Unsupported file type: {ext}")


@router.get("/docs/{doc_id}/file")
def get_file(doc_id: str):
    """Serve raw binary file (image, scanned PDF)."""
    meta_p = _meta_path(doc_id)
    if not meta_p.exists():
        raise HTTPException(404, "doc not found")
    meta = json.loads(meta_p.read_text())
    ext = meta.get("file_ext")
    if not ext:
        raise HTTPException(400, "doc has no binary file")
    fp = _file_path(doc_id, ext)
    if not fp.exists():
        raise HTTPException(404, "file not found")
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf"}
    return FileResponse(fp, media_type=media_types.get(ext, "application/octet-stream"),
                        filename=meta.get("source_file", f"{doc_id}{ext}"))


# ── URL Scrape ──────────────────────────────────────────────────────
@router.post("/scrape")
async def scrape_url(body: ScrapeRequest):
    title, text = _scrape_url_text(body.url)
    doc_id = hashlib.sha256(f"{body.url}{time.time()}".encode()).hexdigest()[:12]
    now = datetime.utcnow().isoformat()
    meta = {
        "id": doc_id, "title": title, "folder": body.folder,
        "tags": body.tags + ["url", "scrape"],
        "created_at": now, "updated_at": now, "size": len(text),
        "content_type": "text", "source_url": body.url,
    }
    _doc_path(doc_id).write_text(text, encoding="utf-8")
    _meta_path(doc_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    await _index_doc(doc_id, title, text, body.folder, meta["tags"])
    return meta


# ── Search ──────────────────────────────────────────────────────────
@router.post("/search")
async def search_docs(body: SearchQuery):
    emb = await _get_embedding(body.query)
    filter_payload = None
    if body.folder:
        filter_payload = {"must": [{"key": "folder", "match": {"value": body.folder}}]}
    r = httpx.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
        json={
            "vector": emb, "limit": body.top_k, "with_payload": True,
            "params": {"hnsw_ef": 128},
            **({"filter": filter_payload} if filter_payload else {}),
        },
    )
    r.raise_for_status()
    hits = r.json()["result"]
    seen = {}
    for h in hits:
        did = h["payload"]["doc_id"]
        if did not in seen or h["score"] > seen[did]["score"]:
            seen[did] = h
    return {"results": list(seen.values())}


@router.get("/folders")
def list_folders():
    folders = set()
    for p in LIBRARY_DIR.glob("*.json"):
        meta = json.loads(p.read_text())
        folders.add(meta.get("folder", "default"))
    return {"folders": sorted(folders)}
