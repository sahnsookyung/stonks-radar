from __future__ import annotations

import asyncio
import logging
import os
import socket
import time

from frw_api.core.logging import configure_logging
from frw_api.db.session import SessionLocal
from frw_api.services.job_queue import claim_job, complete_job, fail_job, heartbeat, reap_expired_leases
from frw_api.services.provider_limits import ProviderLimitError
from frw_worker.tasks import handle_job

configure_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logger.info("worker_started worker_id=%s", worker_id)
    while True:
        with SessionLocal() as db:
            reaped = reap_expired_leases(db)
            if reaped:
                logger.info("reaped_expired_leases count=%s", reaped)
            job = claim_job(db, worker_id=worker_id)
            db.commit()
        if not job:
            await asyncio.sleep(5)
            continue
        started = time.monotonic()
        try:
            async def beat() -> None:
                with SessionLocal() as beat_db:
                    heartbeat(beat_db, job_id=str(job["id"]), worker_id=worker_id)
                    beat_db.commit()

            result = await handle_job(job, beat)
        except Exception as exc:  # noqa: BLE001 - worker must classify unknown failures
            logger.exception("job_failed id=%s", job["id"])
            retry_after_seconds = None
            status_override = None
            retryable = True
            error_class = exc.__class__.__name__
            if isinstance(exc, ProviderLimitError):
                error_class = exc.error_class
                retry_after_seconds = exc.retry_after_seconds
                retryable = exc.retryable
                status_override = "quota_wait" if exc.quota_related else None
            with SessionLocal() as db:
                fail_job(
                    db,
                    job_id=str(job["id"]),
                    error_class=error_class,
                    error_message=str(exc),
                    retryable=retryable,
                    retry_after_seconds=retry_after_seconds,
                    status_override=status_override,
                )
                db.commit()
        else:
            with SessionLocal() as db:
                complete_job(db, job_id=str(job["id"]), result=result)
                db.commit()
            logger.info("job_succeeded id=%s elapsed=%.2f", job["id"], time.monotonic() - started)


if __name__ == "__main__":
    asyncio.run(main())
