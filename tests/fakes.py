"""Fake Voice Transcribe stream for tests (no network)."""

import asyncio


class FakeStream:
    def __init__(self, keywords=None, script=None):
        self.keywords = keywords or []
        self.sent = bytearray()
        self.opened = False
        self.closed = False
        self.queue: asyncio.Queue = asyncio.Queue()
        for ev in script or []:
            self.queue.put_nowait(ev)

    async def open(self):
        self.opened = True

    async def send(self, pcm):
        self.sent.extend(pcm)

    async def events(self):
        while True:
            ev = await self.queue.get()
            if ev is None:
                return
            yield ev

    async def close(self):
        self.closed = True
        self.queue.put_nowait(None)


def run(coro):
    return asyncio.run(coro)
