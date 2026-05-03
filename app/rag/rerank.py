
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.rag.doc_types import DocChunk
from app.settings import settings


def _fallback_lexical(query: str, chunks: list[DocChunk], top_k: int) -> list[DocChunk]:
    """Cheap deterministic rerank when API key missing or model fails."""
    q_tokens = set(query.lower().split())
    scored: list[tuple[float, DocChunk]] = []
    for c in chunks:
        ct = (c.content or "").lower()
        overlap = sum(1 for t in q_tokens if t in ct)
        scored.append((overlap + c.score * 0.1, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:top_k]]


async def rerank_chunks(
    query: str,
    chunks: list[DocChunk],
    top_k: int,
) -> list[DocChunk]:
    if not chunks:
        return []
    k = min(max(top_k, 1), len(chunks))
    if not settings.rerank_enabled or len(chunks) <= k:
        return chunks[:k]

    if not settings.google_api_key:
        return _fallback_lexical(query, chunks, k)

    import google.generativeai as genai  # noqa: PLC0415 — lazy import; package is deprecated

    genai.configure(api_key=settings.google_api_key)
    model = genai.GenerativeModel(settings.adk_model)

    lines = []
    for i, c in enumerate(chunks):
        snippet = (c.content or "")[:1200]
        lines.append(f'{i}\t{c.chunk_id}\t{snippet.replace(chr(10), " ")}')

    prompt = f"""You rank passages for a Helix product support assistant.

Query: {query}

Passages (tab-separated index, chunk_id, text):
{chr(10).join(lines)}

Reply with ONLY valid JSON with key "order": an array of integer indices
(best match first). Include at least {k} indices when possible.
Indices must be between 0 and {len(chunks) - 1}."""

    def _call() -> Any:
        return model.generate_content(
            prompt,
            generation_config={"temperature": 0.1, "max_output_tokens": 512},
        )

    try:
        resp = await asyncio.to_thread(_call)
        raw_text = ""
        if resp.candidates and resp.candidates[0].content.parts:
            raw_text = "".join(p.text or "" for p in resp.candidates[0].content.parts)
        m = re.search(r"\{[\s\S]*\}", raw_text)
        if not m:
            return _fallback_lexical(query, chunks, k)
        data = json.loads(m.group())
        order = data.get("order") or []
        out: list[DocChunk] = []
        seen: set[int] = set()
        for idx in order:
            if isinstance(idx, int) and 0 <= idx < len(chunks) and idx not in seen:
                seen.add(idx)
                out.append(chunks[idx])
            if len(out) >= k:
                break
        for i, c in enumerate(chunks):
            if len(out) >= k:
                break
            if i not in seen:
                out.append(c)
        return out[:k]
    except Exception:
        return _fallback_lexical(query, chunks, k)
