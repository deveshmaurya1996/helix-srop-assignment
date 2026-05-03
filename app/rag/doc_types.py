"""Shared types for retrieval + reranking."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DocChunk:
    chunk_id: str
    score: float
    content: str
    metadata: dict
