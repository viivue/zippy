"""In-memory async job queue.

Each job runs on its own daemon thread. Progress and results are pushed to
subscribers (Server-Sent Events) as they change, and are also available via
polling through Job.to_dict().
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

JOB_STATUSES = ("queued", "running", "done", "failed")


@dataclass
class Job:
    id: str
    kind: str  # "vidopt" | "imgopt" | "imgresize" | "fontslice"
    status: str = "queued"
    progress: float = 0.0  # 0-100, overall job progress
    current_file: str | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _subscribers: list[queue.Queue] = field(
        default_factory=list, repr=False, compare=False
    )
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "current_file": self.current_file,
            "results": self.results,
            "summary": self.summary,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def publish(self) -> None:
        self.updated_at = time.time()
        payload = self.to_dict()
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(payload)

    def set_progress(self, percent: float, current_file: str | None = None) -> None:
        self.progress = max(0.0, min(100.0, percent))
        if current_file is not None:
            self.current_file = current_file
        self.publish()

    def add_result(self, result: dict[str, Any]) -> None:
        self.results.append(result)
        self.publish()

    def set_summary(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        self.publish()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        q.put(self.to_dict())
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


class JobRegistry:
    """Tracks jobs and runs each on its own daemon thread."""

    def __init__(self, max_history: int = 100) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._max_history = max_history

    def create(self, kind: str, run: Callable[[Job], None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._order.insert(0, job.id)
            self._order = self._order[: self._max_history]

        def _worker() -> None:
            job.status = "running"
            job.publish()
            try:
                run(job)
                if job.status != "failed":
                    job.status = "done"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
            job.publish()

        threading.Thread(target=_worker, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            ids = list(self._order)
        return [self._jobs[i] for i in ids if i in self._jobs]
