from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from natural_language_insights import jobs

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

TERMINAL = ("succeeded", "failed")
KEEPALIVE_SECONDS = 15


class Job(BaseModel):
    id: UUID
    kind: str
    dataset_id: UUID
    status: str
    input: dict[str, Any] | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: UUID) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return Job(**job)


@router.get("/{job_id}/events")
async def job_events(job_id: UUID, request: Request) -> StreamingResponse:
    """Server-Sent Events: one `status` event per status change, ending at succeeded/failed."""
    if await anyio.to_thread.run_sync(jobs.get, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    async def stream():
        seen = None
        while not await request.is_disconnected():
            # ponytail: each open stream holds a worker thread while it waits; fine for
            # tens of viewers, move to an asyncio notifier if there are hundreds.
            job = await anyio.to_thread.run_sync(
                jobs.wait_for_change, job_id, seen, KEEPALIVE_SECONDS
            )
            if job["status"] == seen:
                yield ": keep-alive\n\n"
                continue
            seen = job["status"]
            yield f"event: status\ndata: {Job(**job).model_dump_json()}\n\n"
            if seen in TERMINAL:
                return

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
