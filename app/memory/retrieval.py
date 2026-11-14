from typing import Protocol


class MemoryRetriever(Protocol):
    """Phase 2 vector retrieval interface (for example, ChromaDB)."""

    async def retrieve(self, user_id: str, query: str, limit: int = 5) -> list[str]: ...
