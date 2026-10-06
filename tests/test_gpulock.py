import asyncio

from bot.gpulock import GpuLock


async def test_lock_is_seen_by_another_holder(tmp_path):
    # Two GpuLock objects on one file behave like the bot and the web process
    bot, web = GpuLock(tmp_path / "gpu.lock"), GpuLock(tmp_path / "gpu.lock")
    assert not web.locked()
    order = []
    async with bot:
        assert web.locked() and bot.locked()

        async def other():
            async with web:
                order.append("web")
        task = asyncio.create_task(other())
        await asyncio.sleep(0.2)
        order.append("bot done")
    await asyncio.wait_for(task, 2)
    assert order == ["bot done", "web"]
    assert not bot.locked() and not web.locked()
