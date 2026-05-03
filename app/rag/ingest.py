"""CLI: chunk markdown, embed with Chroma default EF, upsert into persistent collection."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
from pathlib import Path

import yaml

from app.rag.vector_store import get_collection

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL | re.MULTILINE)


def extract_metadata(file_path: Path, text: str) -> dict:
    meta: dict = {"source": str(file_path.as_posix())}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return meta
    try:
        fm = yaml.safe_load(m.group(1))
        if isinstance(fm, dict):
            for k in ("title", "product_area", "tags"):
                if k in fm:
                    meta[k] = fm[k]
    except yaml.YAMLError:
        pass
    return meta


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1).strip()


def chunk_markdown(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    body = _strip_frontmatter(text)
    if not body.strip():
        return []

    sections = re.split(r"(?m)^#{2,3}\s+", body)
    chunks: list[str] = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= chunk_size:
            chunks.append(sec)
            continue
        start = 0
        while start < len(sec):
            end = min(start + chunk_size, len(sec))
            piece = sec[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= len(sec):
                break
            start = end - overlap
            if start < 0:
                start = 0
    return [c for c in chunks if c.strip()]


def stable_chunk_id(relative_path: str, index: int) -> str:
    h = hashlib.sha256(f"{relative_path}:{index}".encode()).hexdigest()
    return f"chunk_{h[:20]}"


async def ingest_directory(docs_path: Path, chunk_size: int, chunk_overlap: int) -> None:
    collection = get_collection()
    md_files = sorted(docs_path.rglob("*.md"))
    print(f"Found {len(md_files)} markdown files in {docs_path}")

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for file_path in md_files:
        rel = file_path.relative_to(docs_path).as_posix()
        text = file_path.read_text(encoding="utf-8")
        meta = extract_metadata(file_path, text)
        chunks = chunk_markdown(text, chunk_size, chunk_overlap)
        print(f"  {rel}: {len(chunks)} chunks")
        for i, chunk_text in enumerate(chunks):
            cid = stable_chunk_id(rel, i)
            ids.append(cid)
            documents.append(chunk_text)
            metadatas.append(
                {
                    "chunk_index": i,
                    "source_path": rel,
                    "title": str(meta.get("title", file_path.stem)),
                    "product_area": str(meta.get("product_area", "")),
                }
            )

    if not ids:
        print("No chunks produced — nothing to ingest.")
        return

    batch = 128
    for i in range(0, len(ids), batch):
        await asyncio.to_thread(
            collection.add,
            ids=ids[i : i + batch],
            documents=documents[i : i + batch],
            metadatas=metadatas[i : i + batch],
        )
        print(f"  upserted {min(i + batch, len(ids))}/{len(ids)} chunks")

    print("Ingest complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest docs into the vector store")
    parser.add_argument("--path", type=Path, required=True, help="Directory containing .md files")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--chunk-overlap", type=int, default=64)
    args = parser.parse_args()

    asyncio.run(ingest_directory(args.path, args.chunk_size, args.chunk_overlap))


if __name__ == "__main__":
    main()
