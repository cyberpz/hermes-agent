"""Qdrant + Ollama wrapper for document chunk storage and semantic search."""
import hashlib
import time
from typing import Any, Dict, List, Optional

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


def _point_id(source_path: str, para_index: int) -> str:
    """Generate a deterministic UUID for a (source_path, para_index) pair.

    Qdrant requires point IDs to be either unsigned integers or valid UUIDs.
    SHA1-truncated hex (24 chars) is neither → 400 Bad Request.
    """
    import uuid as _uuid
    h = hashlib.sha1(f"{source_path}::{para_index}".encode()).hexdigest()
    return str(_uuid.UUID(h))


class RagStore:
    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        ollama_url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
        collection: str = "documents_chunks",
    ):
        self.qdrant_url = qdrant_url
        self.ollama_url = ollama_url
        self.embed_model = embed_model
        self.collection = collection
        self.client = QdrantClient(url=qdrant_url, timeout=60.0)
        self._ensure_collection()

    def _ensure_collection(self):
        """Create the Qdrant collection if it doesn't exist.

        nomic-embed-text produces 768-dim vectors. We hardcode that here so
        we don't depend on a probe embedding succeeding in sync context.
        """
        try:
            self.client.get_collection(self.collection)
            return
        except Exception:
            pass
        try:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=768, distance=qm.Distance.COSINE),
            )
        except Exception:
            # Race or already exists
            pass

    async def _embed(self, text: str) -> List[float]:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=60.0,
            )
            r.raise_for_status()
            return r.json()["embedding"]

    async def upsert(
        self,
        chunks: List[Dict[str, Any]],
        source_path: str,
        title: str = "",
        folder: str = "default",
        tags: Optional[List[str]] = None,
    ) -> int:
        tags = tags or []
        points = []
        for ch in chunks:
            vec = await self._embed(ch["text"])
            payload = {
                "text": ch["text"],
                "source_path": source_path,
                "title": title,
                "folder": folder,
                "tags": tags,
                "heading_path": ch.get("heading_path", []),
                "paragraph_index": ch.get("paragraph_index"),
                "char_start": ch.get("char_start"),
                "char_end": ch.get("char_end"),
                "kind": ch.get("kind", "text"),
                "indexed_at": time.time(),
            }
            pid = _point_id(source_path, ch.get("paragraph_index", 0))
            points.append(qm.PointStruct(id=pid, vector=vec, payload=payload))
        if not points:
            return 0
        # batch in chunks of 64
        for i in range(0, len(points), 64):
            self.client.upsert(collection_name=self.collection, points=points[i : i + 64])
        return len(points)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        folder: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        vec = await self._embed(query)
        flt = None
        if folder:
            flt = qm.Filter(
                must=[qm.FieldCondition(key="folder", match=qm.MatchValue(value=folder))]
            )
        try:
            res = self.client.search(
                collection_name=self.collection,
                query_vector=vec,
                limit=top_k,
                with_payload=True,
                query_filter=flt,
            )
        except Exception:
            return []
        out = []
        for r in res:
            out.append(
                {
                    "id": getattr(r, "id", None),
                    "score": float(getattr(r, "score", 0.0)),
                    "payload": getattr(r, "payload", {}) or {},
                }
            )
        return out
