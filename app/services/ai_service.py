import logging
import asyncio
from collections.abc import AsyncIterator
from time import perf_counter

from openai import APIError, AsyncOpenAI

from app.core.config import Settings
from app.services.provider_budget import reserve_provider_call
from app.services.voice_trace import mark_voice_stage
from app.services.request_limits import provider_slot

logger = logging.getLogger(__name__)


class AIService:
    def __init__(
        self, settings: Settings, provider_semaphore: asyncio.Semaphore | None = None
    ) -> None:
        self._settings = settings
        self._provider_semaphore = provider_semaphore
        self._client: AsyncOpenAI | None = None

    def _client_or_raise(self) -> AsyncOpenAI:
        if not self._settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        if self._client is None:
            client_options: dict[str, object] = {
                "api_key": self._settings.openrouter_api_key,
                "base_url": "https://openrouter.ai/api/v1",
                "timeout": 60.0,
                "default_headers": {
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Bella AI Cloud",
                },
            }
            if getattr(self._settings, "voice_test_enabled", False):
                # The SDK otherwise retries selected failures automatically.
                client_options["max_retries"] = 0
            self._client = AsyncOpenAI(
                **client_options,  # type: ignore[arg-type]
            )
        return self._client

    async def reply(self, messages: list[dict[str, str]]) -> str:
        start = perf_counter()
        try:
            async with provider_slot(self._provider_semaphore):
                await reserve_provider_call(
                    "openrouter_chat",
                    required=getattr(self._settings, "voice_test_enabled", False),
                )
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
        client_reused = self._client is not None
        client = self._client_or_raise()
        context_chars = sum(
            len(content) for message in messages
            if isinstance((content := message.get("content")), str)
        )
        estimated_tokens = (context_chars + 3) // 4
        mark_voice_stage(
            "llm_request_prepared",
            duration_seconds=perf_counter() - start,
            message_count=len(messages),
            context_chars=context_chars,
            estimated_input_tokens=estimated_tokens,
            status="reused_client" if client_reused else "new_client",
        )
        mark_voice_stage("llm_request_started")
        first_event_at: float | None = None
        first_delta_at: float | None = None
        event_count = 0
        try:
            slot_wait_started = perf_counter()
            async with provider_slot(self._provider_semaphore):
                mark_voice_stage(
                    "llm_provider_slot_acquired",
                    duration_seconds=perf_counter() - slot_wait_started,
                )
                await reserve_provider_call(
                    "openrouter_chat",
                    required=getattr(self._settings, "voice_test_enabled", False),
                )
                request_started = perf_counter()
                mark_voice_stage(
                    "llm_http_request_started",
                    provider_model=self._settings.model_name,
                    retry_policy=(
                        "disabled"
                        if getattr(self._settings, "voice_test_enabled", False)
                        else "sdk_default"
                    ),
                )
                stream = await client.chat.completions.create(
                    model=self._settings.model_name,
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=self._settings.max_tokens,
                    stream=True,
                )
                headers_received_at = perf_counter()
                mark_voice_stage(
                    "llm_http_response_received",
                    duration_seconds=headers_received_at - request_started,
                    provider_model=self._settings.model_name,
                )
                async for chunk in stream:
                    event_count += 1
                    if first_event_at is None:
                        first_event_at = perf_counter()
                        mark_voice_stage(
                            "llm_first_stream_event",
                            duration_seconds=first_event_at - request_started,
                            events=event_count,
                        )
                        mark_voice_stage(
                            "llm_first_event_after_headers",
                            duration_seconds=first_event_at - headers_received_at,
                        )
                        provider = getattr(chunk, "provider", None)
                        if isinstance(provider, str) and provider:
                            mark_voice_stage("llm_provider_metadata", provider=provider)
                        routed_model = getattr(chunk, "model", None)
                        if isinstance(routed_model, str) and routed_model:
                            mark_voice_stage(
                                "llm_model_metadata", provider_model=routed_model
                            )
                    if not chunk.choices:
                        continue
                    content = chunk.choices[0].delta.content
                    if isinstance(content, str) and content:
                        if first_delta_at is None:
                            first_delta_at = perf_counter()
                            elapsed = first_delta_at - start
                            logger.info("GPT first token time: %.2fs", elapsed)
                            mark_voice_stage(
                                "llm_first_delta",
                                duration_seconds=elapsed,
                            )
                            mark_voice_stage(
                                "llm_first_delta_after_headers",
                                duration_seconds=first_delta_at - headers_received_at,
                            )
                        yield content
            completed_at = perf_counter()
            elapsed = completed_at - start
            logger.info("GPT time: %.2fs", elapsed)
            mark_voice_stage("llm_provider_stream_complete", duration_seconds=elapsed)
            if first_delta_at is not None:
                mark_voice_stage(
                    "llm_remaining_generation",
                    duration_seconds=completed_at - first_delta_at,
                    events=event_count,
                )
        except (APIError, IndexError, TypeError) as error:
            logger.exception("OpenRouter streaming request failed")
            raise RuntimeError("AI provider streaming request failed") from error

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
