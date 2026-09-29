"""Background jobs: persisted in DuckDB, executed on an in-process thread pool."""

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

from natural_language_insights.config.settings import settings
from natural_language_insights.database import db_query, db_records

logger = logging.getLogger(__name__)

# ponytail: in-process pool, work is lost on crash (marked failed on restart).
# Swap for a real queue (arq/Celery + Redis) when running more than one API process.
executor = ThreadPoolExecutor(max_workers=settings.job_workers)

# Signalled on every status change so streams wake up instead of polling the database.
# ponytail: in-process only, like the pool; use Redis pub/sub or Postgres LISTEN with >1 process.
_changed = threading.Condition()


class JobError(Exception):
    """A failure whose message is safe to show to the caller."""


def submit(
    kind: str,
    dataset_id: UUID,
    payload: dict,
    work: Callable[[], dict],
    conversation_id: UUID | None = None,
) -> UUID:
    job_id = uuid4()
    db_query(
        "INSERT INTO jobs (id, kind, dataset_id, conversation_id, status, input) "
        "VALUES (?, ?, ?, ?, 'queued', ?)",
        [job_id, kind, dataset_id, conversation_id, json.dumps(payload)],
    )
    executor.submit(_run, job_id, work)
    return job_id


def get(job_id: UUID) -> dict | None:
    rows = db_records("SELECT * FROM jobs WHERE id = ?", [job_id])
    if not rows:
        return None
    job = rows[0]
    for field in ("input", "result"):
        if job[field] is not None:
            job[field] = json.loads(job[field])
    return job


def wait_for_change(job_id: UUID, seen_status: str | None, timeout: float) -> dict | None:
    """Block until the job's status differs from seen_status, or timeout. Returns the job."""
    deadline = time.monotonic() + timeout
    # Reading and waiting under the same lock: an update between the read and the wait
    # can't notify until we are waiting, so no change is missed.
    with _changed:
        while True:
            job = get(job_id)
            remaining = deadline - time.monotonic()
            if job is None or job["status"] != seen_status or remaining <= 0:
                return job
            _changed.wait(remaining)


def _run(job_id: UUID, work: Callable[[], dict]) -> None:
    _update(job_id, "running")
    try:
        result = work()
    except JobError as exc:
        _update(job_id, "failed", error=str(exc))
    except Exception:
        logger.exception("Job %s crashed", job_id)
        _update(job_id, "failed", error="Internal error while running the job.")
    else:
        _update(job_id, "succeeded", result=result)


def _update(job_id: UUID, status: str, result: dict | None = None, error: str | None = None):
    db_query(
        "UPDATE jobs SET status = ?, result = ?, error = ?, updated_at = now() WHERE id = ?",
        [
            status,
            None if result is None else json.dumps(result, default=to_json),
            error,
            job_id,
        ],
    )
    with _changed:
        _changed.notify_all()


def to_json(value):
    return float(value) if isinstance(value, Decimal) else str(value)
