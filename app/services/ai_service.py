import logging
from time import perf_counter
from collections.abc import AsyncIterator

from openai import APIError, AsyncOpenAI

from app.core.config import Settings
from app.services.voice_trace import mark_voice_stage

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    def _client_or_raise(self) -> AsyncOpenAI:
        if not self._settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                timeout=60.0,
                default_headers={
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Bella AI Cloud",
                },
            )
        return self._client

    async def reply(self, messages: list[dict[str, str]]) -> str:
        start = perf_counter()
        try:
            response = await self._client_or_raise().chat.completions.create(
                model=self._settings.model_name,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=self._settings.max_tokens,
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("The AI provider returned an empty reply")
            logger.info("GPT time: %.2fs", perf_counter() - start)
            return content.strip()
        except (APIError, IndexError, TypeError) as error:
            logger.exception("OpenRouter request failed")
            raise RuntimeError("AI provider request failed") from error

    async def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield OpenRouter response tokens as they arrive."""
        start = perf_counter()
        first_token_logged = False
        mark_voice_stage("llm_request_started")
        try:
            stream = await self._client_or_raise().chat.completions.create(
                model=self._settings.model_name,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=self._settings.max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if isinstance(content, str) and content:
                    if not first_token_logged:
                        elapsed = perf_counter() - start
                        logger.info("GPT first token time: %.2fs", elapsed)
                        mark_voice_stage(
                            "llm_first_delta",
                            duration_seconds=elapsed,
                        )
                        first_token_logged = True
                    yield content
            elapsed = perf_counter() - start
            logger.info("GPT time: %.2fs", elapsed)
            mark_voice_stage("llm_provider_stream_complete", duration_seconds=elapsed)
        except (APIError, IndexError, TypeError) as error:
            logger.exception("OpenRouter streaming request failed")
            raise RuntimeError("AI provider streaming request failed") from error

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
