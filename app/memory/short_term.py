import asyncio
import uuid
from collections import defaultdict, deque

from app.core.schemas import Message


class ShortTermMemory:
    """Session history contract; replace with Redis in Phase 2 without route changes."""

    def __init__(self, limit: int = 20) -> None:
        self._limit = limit
        self._sessions: dict[str, deque[Message]] = defaultdict(lambda: deque(maxlen=limit))
        self._lock = asyncio.Lock()

    async def session_id(self, provided: str | None = None) -> str:
        return provided or str(uuid.uuid4())

    async def get_history(self, session_id: str) -> list[Message]:
        async with self._lock:
            return list(self._sessions[session_id])

    async def add(self, session_id: str, message: Message) -> None:
        async with self._lock:
            self._sessions[session_id].append(message)
