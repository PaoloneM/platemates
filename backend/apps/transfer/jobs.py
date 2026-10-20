"""Running imports in the worker (`manage.py worker`), their progress announced to the
administrators in real time (`ADMIN_ROOM`, event `transfer`). The page also reloads the job from
the API, so a lost message only delays the bar."""

from __future__ import annotations

import logging
import time

from django.db import connection, transaction
from django.utils import timezone

from apps.realtime.events import ADMIN_ROOM, publish_to

from .importing import TransferError, import_document
from .models import ImportJob

log = logging.getLogger(__name__)

# PostgreSQL channel on which a queued import wakes the worker up.
CHANNEL = "transfer_jobs"
# Progress is saved and announced at most this often (an import can have thousands of items).
ANNOUNCE_SECONDS = 0.5


def notify_worker() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_notify(%s, '')", [CHANNEL])


def announce(job: ImportJob) -> None:
    publish_to(
        ADMIN_ROOM,
        "transfer",
        {
            "id": job.pk,
            "status": job.status,
            "phase": job.phase,
            "done": job.done,
            "total": job.total,
        },
    )


def run_job(job: ImportJob) -> None:
    last = 0.0

    def progress(phase: str, done: int, total: int) -> None:
        nonlocal last
        job.phase, job.done, job.total = phase, done, total
        now = time.monotonic()
        if now - last >= ANNOUNCE_SECONDS or done >= total:
            last = now
            # Outside the import's transaction: a separate save would wait for it, so only the
            # announcement goes out now; the row is saved at the end.
            announce(job)

    try:
        report = import_document(
            job.document,
            user=job.created_by,
            mode=job.mode,
            target_team=job.target_team,
            dry_run=job.dry_run,
            progress=progress,
        )
        summary = {k: job.document.get(k) for k in ("scope", "exported_at")}
        job.report = {**report.as_dict(), "document": summary}
        job.status = ImportJob.Status.DONE
        if not job.dry_run:
            # Imported for real: the file is not needed any more.
            job.document = {}
    except TransferError as exc:
        job.status, job.error = ImportJob.Status.FAILED, str(exc)
    except Exception as exc:
        log.exception("import %s crashed", job.pk)
        job.status, job.error = ImportJob.Status.FAILED, f"Unexpected error: {exc}"[:2000]
    job.finished_at = timezone.now()
    job.save()
    announce(job)


def claim_next() -> ImportJob | None:
    with transaction.atomic():
        job = (
            ImportJob.objects.select_for_update(skip_locked=True)
            .filter(status=ImportJob.Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None
        job.status = ImportJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
    announce(job)
    return job


def fail_interrupted() -> int:
    return ImportJob.objects.filter(status=ImportJob.Status.RUNNING).update(
        status=ImportJob.Status.FAILED,
        error="Interrupted: the worker stopped before finishing. Nothing was imported.",
        finished_at=timezone.now(),
    )
