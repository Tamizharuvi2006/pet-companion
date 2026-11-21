import asyncio
from types import SimpleNamespace

from app.core.config import Settings
from app.services.audio_reply_service import AudioReplyService, AudioReplyTurn


def test_audio_reply_replaces_only_current_placeholder_and_closes_on_cancel():
    async def run():
        closed = asyncio.Event()
        service = AudioReplyService(Settings(openrouter_api_key='offline'))
        captured = {}

        class Stream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()

            async def close(self):
                closed.set()

        async def create(**kwargs):
            captured.update(kwargs)
            return Stream()

        await service.client.close()
        service.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        messages = [{'role': 'system', 'content': 'Bella'},
                    {'role': 'user', 'content': 'My name is Sam'},
                    {'role': 'assistant', 'content': 'Hello Sam.'},
                    {'role': 'user', 'content': '[Voice message; transcript not retained]'}]
        stream = AudioReplyTurn(service, 'encoded-fixture').stream_reply(messages)
        task = asyncio.create_task(anext(stream))
        for _ in range(20):
            await asyncio.sleep(0)
            if captured:
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert closed.is_set()
        assert messages[-1]['content'] == '[Voice message; transcript not retained]'
        assert captured['messages'][:-1] == messages[:-1]
        assert captured['messages'][-1]['content'][0]['input_audio']['format'] == 'wav'
        assert captured['model'] == 'openai/gpt-audio-mini'

    asyncio.run(run())
