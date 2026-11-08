"""
Periodic evaluation.

A single daemon thread wakes up on a short tick and starts a run when
``AI_EVAL_SCHEDULE_HOURS`` has elapsed. Using a tick instead of one long
``sleep`` means the schedule reacts to configuration changes and to
shutdown promptly, and a clock jump cannot stall the loop forever.

Scheduling is off by default (``AI_EVAL_SCHEDULE_HOURS=0``). When it is
enabled, the scheduled run uses ``AI_EVAL_SCHEDULE_LIMIT`` samples so a
nightly job stays cheap on a CPU-only deployment.
"""

import logging
import threading
import time

from .jobs import EvaluationBusy
from .runner import RunRequest


logger = logging.getLogger(__name__)

# How often the loop checks the clock. Short enough to notice a stop
# request quickly, long enough to be free.
TICK_SECONDS = 30.0

# Do not start a scheduled run while the models are still loading.
READY_WAIT_SECONDS = 30.0


class EvaluationScheduler:
    def __init__(self, registry, runner_factory, config, *, is_ready=None):
        self.registry = registry
        self.runner_factory = runner_factory
        self.config = config
        self.is_ready = is_ready

        self._stop_event = threading.Event()
        self._thread = None
        self._last_run_at = None
        self._last_error = None
        self._runs_started = 0

    @property
    def enabled(self):
        return self.config.schedule_enabled

    def start(self):
        if not self.enabled:
            logger.info(
                "Evaluation scheduler disabled "
                "(AI_EVAL_SCHEDULE_HOURS is 0)."
            )
            return None

        if self._thread is not None and self._thread.is_alive():
            return self._thread

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="eval-scheduler",
            daemon=True,
        )
        self._thread.start()

        logger.info(
            "Evaluation scheduler started: every %s hours, %s samples.",
            self.config.schedule_hours,
            self.config.schedule_limit,
        )

        return self._thread

    def stop(self):
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=5)

    def status(self):
        return {
            "enabled": self.enabled,
            "interval_hours": self.config.schedule_hours,
            "sample_limit": self.config.schedule_limit,
            "runs_started": self._runs_started,
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "thread_alive": bool(
                self._thread is not None and self._thread.is_alive()
            ),
        }

    def _loop(self):
        interval_seconds = max(60.0, self.config.schedule_hours * 3600.0)

        # A small initial delay avoids competing with the startup
        # migrations and the first model load.
        if self._stop_event.wait(min(interval_seconds, 120.0)):
            return

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:  # pragma: no cover - defensive
                self._last_error = str(exc)[:300]
                logger.exception("Evaluation scheduler tick failed")

            if self._stop_event.wait(TICK_SECONDS):
                return

    def _tick(self):
        now = time.monotonic()

        if self._last_run_at is not None:
            elapsed = now - self._last_run_at

            if elapsed < self.config.schedule_hours * 3600.0:
                return

        if self.is_ready is not None:
            try:
                if not self.is_ready(READY_WAIT_SECONDS):
                    return
            except Exception:
                return

        if self.registry.is_running:
            logger.info(
                "Scheduled evaluation skipped: another run is in progress."
            )
            self._last_run_at = now
            return

        request = RunRequest(
            limit=self.config.schedule_limit,
            triggered_by="schedule",
        )

        try:
            self.registry.start(
                self.runner_factory(),
                request,
                triggered_by="schedule",
            )
            self._runs_started += 1
            self._last_error = None

        except EvaluationBusy:
            logger.info(
                "Scheduled evaluation skipped: registry is busy."
            )

        except Exception as exc:
            self._last_error = str(exc)[:300]
            logger.exception("Scheduled evaluation could not start")

        self._last_run_at = now
