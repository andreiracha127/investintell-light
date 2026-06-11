"""Shared list-chunking helper for bulk DB statements.

asyncpg hard-limits query parameters to 32 767 (INT16_MAX), so every bulk
upsert in the project executes in chunks. Each call site sizes its chunk so
``rows_per_chunk x params_per_row`` stays safely under that ceiling — the
rationale is documented next to each chunk-size constant.
"""

from collections.abc import Iterator


def chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    """Yield consecutive slices of *items* with at most *size* elements each.

    An empty list yields nothing. Order is preserved; the last chunk may be
    shorter than *size*.

    Raises:
        ValueError: if ``size < 1``.
    """
    if size < 1:
        raise ValueError(f"chunked requires size >= 1, got {size}")
    for start in range(0, len(items), size):
        yield items[start : start + size]
