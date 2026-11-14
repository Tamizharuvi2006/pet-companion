import asyncio

from app.api.websocket import _finish_interim_before_final


def test_capture_id_client_does_not_wait_for_interim_whisper() -> None:
    async def run() -> None:
        release_interim = asyncio.Event()

        async def pending_interim() -> None:
            await release_interim.wait()

        task = asyncio.create_task(pending_interim())
        await _finish_interim_before_final(task, "capture-123")
        assert not task.done()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_legacy_client_still_waits_for_interim_whisper() -> None:
    async def run() -> None:
        partial_finished = asyncio.Event()

        async def pending_interim() -> None:
            await asyncio.sleep(0)
            partial_finished.set()

        task = asyncio.create_task(pending_interim())
        await _finish_interim_before_final(task, None)
        assert partial_finished.is_set()

    asyncio.run(run())
