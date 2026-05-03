from __future__ import annotations

import pytest

from app.rag import ingest
from app.settings import settings


@pytest.mark.asyncio
async def test_search_docs_returns_results_with_chunk_ids(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "t.md").write_text(
        "---\ntitle: Test\nproduct_area: security\n---\n\n## A\n\nHello world security content.\n",
        encoding="utf-8",
    )
    chroma = tmp_path / "chroma"
    monkeypatch.setattr(settings, "chroma_persist_dir", str(chroma))

    await ingest.ingest_directory(docs, chunk_size=200, chunk_overlap=32)

    from app.agents.tools.search_docs import search_docs

    results = await search_docs("security content", k=3)
    assert len(results) > 0
    assert all(r.chunk_id for r in results)
    assert all(0.0 <= r.score <= 1.0 for r in results)


def test_chunker_produces_non_empty_chunks():
    from app.rag.ingest import chunk_markdown

    text = "# Header\n\nSome content.\n\n## Section 2\n\nMore content here."
    chunks = chunk_markdown(text, chunk_size=100, overlap=20)
    assert len(chunks) > 0
    assert all(c.strip() for c in chunks)
