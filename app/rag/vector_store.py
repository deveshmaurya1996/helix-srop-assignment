from __future__ import annotations

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from app.settings import settings

COLLECTION_NAME = "helix_docs"

_ef = embedding_functions.DefaultEmbeddingFunction()


def get_chroma_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_collection() -> Collection:
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_ef,
        metadata={"hnsw:space": "cosine"},
    )


def distance_to_score(distance: float) -> float:
    """Map Chroma distance to a similarity score in [0, 1]."""
    d = float(distance)
    if d < 0:
        d = 0.0
    return max(0.0, min(1.0, 1.0 / (1.0 + d)))
