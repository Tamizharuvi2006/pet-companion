from typing import Protocol


class LongTermMemory(Protocol):
    """Phase 2 PostgreSQL store interface for durable user facts."""

    async def save_fact(self, user_id: str, fact: str, importance: float) -> None: ...

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]: ...
