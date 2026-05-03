"""Buffers chunk IDs from ``search_docs`` for ``agent_traces.retrieved_chunk_ids``."""
from contextvars import ContextVar

_chunk_ids: ContextVar[list[str] | None] = ContextVar("chunk_ids", default=None)


def reset_trace_buffers() -> None:
    _chunk_ids.set([])


def record_chunk_ids(ids: list[str]) -> None:
    buf = _chunk_ids.get()
    if buf is not None:
        buf.extend(ids)


def get_recorded_chunk_ids() -> list[str]:
    buf = _chunk_ids.get()
    return list(buf) if buf else []
