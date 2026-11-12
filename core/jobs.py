"""Run AI tasks in the background so the page can show progress instead of hanging."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .ai import AIError
from .services import ServiceError
from .store import Store

log = logging.getLogger("documentor.jobs")


class JobRunner:
    def __init__(self, store: Store, handlers: dict[str, Callable], workers: int = 2):
        self.store = store
        self.handlers = handlers
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="documentor-job")

    def submit(self, job_type: str, params: dict) -> str:
        job_id = self.store.create_job(job_type, params)
        self.pool.submit(self._run, job_id, job_type, params)
        return job_id

    def _run(self, job_id: str, job_type: str, params: dict) -> None:
        def progress(percent: int, message: str) -> None:
            self.store.update_job(job_id, status="running", progress=percent, message=message)

        progress(1, "Starting")
        try:
            output = self.handlers[job_type](params, progress)
        except AIError as exc:
            self.store.update_job(job_id, status="failed", error_code=exc.code, error=exc.message)
        except ServiceError as exc:
            self.store.update_job(job_id, status="failed", error_code="invalid", error=str(exc))
        except Exception:  # never show internals to the user; the log keeps the detail
            log.exception("Job %s (%s) failed", job_id, job_type)
            self.store.update_job(job_id, status="failed", error_code="internal",
                                  error="Something went wrong on our side. Please try again.")
        else:
            self.store.update_job(job_id, status="done", progress=100, message="Done", output=output)
