"""ADK tool: Chroma retrieval, optional rerank (E4), chunk IDs for traces."""
from __future__ import annotations

from app.agents.trace_context import record_chunk_ids
from app.rag.doc_types import DocChunk
from app.rag.rerank import rerank_chunks
from app.rag.vector_store import distance_to_score, get_collection
from app.settings import settings


async def search_docs(query: str, k: int = 5, product_area: str | None = None) -> list[DocChunk]:
    collection = get_collection()
    import asyncio

    q = query.strip()
    if not q:
        return []

    oversample = settings.rerank_oversample if settings.rerank_enabled else 1
    n_fetch = min(max(k * max(oversample, 1), 1), 50)  # fetch more than k when reranking

    def _query():
        return collection.query(
            query_texts=[q],
            n_results=n_fetch,
            include=["documents", "distances", "metadatas"],
        )

    raw = await asyncio.to_thread(_query)  # Chroma client is sync; keep event loop unblocked
    ids_list = raw.get("ids") or []
    docs_list = raw.get("documents") or []
    dist_list = raw.get("distances") or []
    meta_list = raw.get("metadatas") or []

    if not ids_list or not ids_list[0]:
        return []

    ids = ids_list[0]
    docs = docs_list[0] if docs_list else []
    dists = dist_list[0] if dist_list else [0.0] * len(ids)
    metas = meta_list[0] if meta_list else [{}] * len(ids)

    out: list[DocChunk] = []
    chunk_ids: list[str] = []
    for i, cid in enumerate(ids):
        doc = docs[i] if i < len(docs) else ""
        meta = metas[i] if i < len(metas) else {}
        if not isinstance(meta, dict):
            meta = {}
        if product_area and meta.get("product_area") not in (None, "", product_area):
            continue
        dist = float(dists[i]) if i < len(dists) else 0.0
        score = distance_to_score(dist)
        out.append(DocChunk(chunk_id=cid, score=score, content=doc or "", metadata=meta))
        chunk_ids.append(cid)

    out.sort(key=lambda c: c.score, reverse=True)
    if settings.rerank_enabled and len(out) > k:
        out = await rerank_chunks(q, out, k)
    else:
        out = out[:k]
    record_chunk_ids([c.chunk_id for c in out])
    return out
