"""
In-process job registry for evaluation runs.

A run can take minutes on CPU-only hardware, so it always executes on a
background thread and the caller polls for progress. Only one run may be
active at a time: the LLM and the embedding model are already serialised
behind a semaphore, and two concurrent evaluations would simply halve
each other's speed while doubling memory pressure.

The registry keeps a bounded history. Full reports live on disk; only
the summary stays in memory, so a long-running service cannot leak.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone

from .runner import RunRequest


logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EvaluationBusy(RuntimeError):
    """Another evaluation run is already in progress."""


class JobRegistry:
    def __init__(self, *, max_history=20):
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._jobs = {}
        self._order = []
        self._max_history = max(1, max_history)
        self._active_job_id = None

    # -- introspection ---------------------------------------------------

    @property
    def is_running(self):
        return self._active_job_id is not None

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, limit=20):
        with self._lock:
            jobs = [
                dict(self._jobs[job_id])
                for job_id in reversed(self._order)
                if job_id in self._jobs
            ]

        return jobs[:limit]

    def summary(self):
        with self._lock:
            return {
                "running": self._active_job_id is not None,
                "active_job_id": self._active_job_id,
                "jobs": len(self._jobs),
            }

    # -- lifecycle -------------------------------------------------------

    def start(self, runner, request, *, triggered_by="api"):
        """
        Start a run on a daemon thread.

        Raises :class:`EvaluationBusy` when a run is already active so
        the endpoint can answer 409 instead of silently queueing work
        that would never be visible to the caller.
        """

        if not self._run_lock.acquire(blocking=False):
            raise EvaluationBusy(
                "An evaluation run is already in progress. "
                "Poll its status before starting another one."
            )

        job_id = uuid.uuid4().hex[:12]

        job = {
            "job_id": job_id,
            "status": STATUS_QUEUED,
            "triggered_by": triggered_by,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
            "progress": {"processed": 0, "total": 0, "current": None},
            "summary": None,
            "report_paths": None,
            "error": None,
        }

        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._active_job_id = job_id
            self._trim()

        thread = threading.Thread(
            target=self._execute,
            args=(job_id, runner, request),
            name=f"eval-{job_id}",
            daemon=True,
        )
        thread.start()

        return dict(job)

    def _trim(self):
        while len(self._order) > self._max_history:
            oldest = self._order.pop(0)

            if oldest == self._active_job_id:
                # Never drop the job that is still running.
                self._order.append(oldest)
                break

            self._jobs.pop(oldest, None)

    def _update(self, job_id, **fields):
        with self._lock:
            job = self._jobs.get(job_id)

            if job is None:
                return

            job.update(fields)

    def _execute(self, job_id, runner, request):
        self._update(
            job_id,
            status=STATUS_RUNNING,
            started_at=_now_iso(),
        )

        def on_progress(processed, total, current):
            self._update(
                job_id,
                progress={
                    "processed": processed,
                    "total": total,
                    "current": current,
                },
            )

        try:
            report = runner.run(request, progress=on_progress)

            self._update(
                job_id,
                status=STATUS_SUCCEEDED,
                finished_at=_now_iso(),
                summary=report.get("summary"),
                report_paths=report.get("report_paths"),
                progress={
                    "processed": len(report.get("samples") or []),
                    "total": len(report.get("samples") or []),
                    "current": None,
                },
            )

        except Exception as exc:
            logger.exception("Evaluation job %s failed", job_id)
            self._update(
                job_id,
                status=STATUS_FAILED,
                finished_at=_now_iso(),
                error=f"{type(exc).__name__}: {exc}"[:500],
            )

        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

            self._run_lock.release()


def build_request(payload):
    """Translate a JSON request body into a :class:`RunRequest`."""

    if payload is None:
        return RunRequest(triggered_by="api")

    if not isinstance(payload, dict):
        raise ValueError("The request body must be a JSON object.")

    department_ids = payload.get("department_ids") or ()

    if isinstance(department_ids, int):
        department_ids = (department_ids,)

    sample_ids = payload.get("sample_ids") or ()

    if isinstance(sample_ids, str):
        sample_ids = (sample_ids,)

    metrics = payload.get("metrics") or ()

    if isinstance(metrics, str):
        metrics = tuple(
            part.strip() for part in metrics.split(",") if part.strip()
        )

    limit = payload.get("limit")

    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError("'limit' must be an integer.")

        if limit <= 0:
            raise ValueError("'limit' must be greater than zero.")

    top_k = payload.get("top_k")

    if top_k is not None:
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            raise ValueError("'top_k' must be an integer.")

    tenant_id = payload.get("tenant_id")

    if tenant_id is not None:
        try:
            tenant_id = int(tenant_id)
        except (TypeError, ValueError):
            raise ValueError("'tenant_id' must be an integer.")

    return RunRequest(
        tenant_id=tenant_id,
        department_ids=tuple(int(value) for value in department_ids),
        limit=limit,
        sample_ids=tuple(str(value) for value in sample_ids),
        metrics=tuple(metrics),
        top_k=top_k,
        triggered_by="api",
    )
