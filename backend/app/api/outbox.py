"""A socket's outbound queue.

Runs deliver frames to every socket watching them by a plain call
(services/live.py), which must never wait on a slow or vanished client. Each
connection puts frames on its own queue, in the order they were delivered,
and one writer task sends them.
"""

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)


class Outbox:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self._queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def deliver(self, frame: dict) -> None:
        """Queue a frame; dropped once the socket is gone."""
        if not self.closed:
            self._queue.put_nowait(frame)

    async def drain(self) -> None:
        """Send queued frames until the socket fails or the task is cancelled."""
        try:
            while True:
                frame = await self._queue.get()
                await self.websocket.send_json(frame)
        except (RuntimeError, WebSocketDisconnect):
            pass
        finally:
            self.closed = True
