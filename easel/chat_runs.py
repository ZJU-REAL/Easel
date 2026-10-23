"""Async chat lifecycle adapter; never replays an agent request."""
from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

from easel.run_store import RunRecord, RunStore


async def durable_call(operation):
    """Wait for a short database write even if its caller is cancelled.

    Cancelling to_thread does not stop its worker. Waiting preserves the order
    between a persisted transition, cancellation cleanup and lock release.
    """
    pending = asyncio.create_task(asyncio.to_thread(operation))
    cancellation = None
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as error:
            if pending.cancelled():
                raise
            cancellation = error
    result = pending.result()
    if cancellation is not None:
        raise cancellation
    return result


class DirectChatRun:
    def __init__(self, path: Path, backend: str = "direct_api"):
        self.path = path
        self.backend = backend
        self.record: RunRecord | None = None
        self.owner_id = uuid.uuid4().hex

    async def create(self, turn_id: str, session_id: str) -> None:
        def write():
            self.record = RunStore(self.path).create(turn_id, session_id, self.backend)
        try:
            await durable_call(write)
        except asyncio.CancelledError:
            if self.record is not None:
                await self.transition("cancelled")
            raise

    async def transition(self, state: str) -> None:
        def write():
            current = self.record
            if current is None:
                raise RuntimeError("Chat run was not created")
            self.record = RunStore(self.path).transition(
                current.turn_id, expected_version=current.version, state=state,
                owner_id=self.owner_id if current.state == "running" or state == "running" else None,
            )
        await durable_call(write)
