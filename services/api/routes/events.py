"""SSE progress stream for a run.

Events are replayed from the durable ``events.jsonl`` log, so a browser
reconnecting mid-run loses nothing; the stream closes with a ``done``
event once the run reaches a terminal status.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from repomate_core.contracts import ErrorCode
from repomate_core.orchestration.store_factory import build_store
from services.api.config import SSE_MAX_SECONDS, SSE_POLL_SECONDS, read_settings
from services.api.errors import api_error

router = APIRouter(prefix="/api/runs/{run_id}")


@router.get("/events")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    store = build_store(read_settings().runs_root, read_settings().database_url)
    if store.load_run(run_id) is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"unknown run: {run_id}")

    async def generator():
        last_seq = 0
        deadline = asyncio.get_event_loop().time() + SSE_MAX_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            if await request.is_disconnected():
                return
            for event in store.load_events(run_id, after_seq=last_seq):
                last_seq = event.seq
                payload = json.dumps(event.model_dump(mode="json"), default=str)
                yield f"event: progress\ndata: {payload}\n\n"
            record = store.load_run(run_id)
            if record is not None and record.is_terminal:
                yield (
                    "event: done\ndata: "
                    + json.dumps({"run_id": run_id, "status": record.status.value})
                    + "\n\n"
                )
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
