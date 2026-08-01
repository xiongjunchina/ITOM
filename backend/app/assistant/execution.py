"""Bounded admission for synchronous assistant capability workers."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import Any, Callable


class ToolExecutorSaturated(RuntimeError):
    """Raised before submission when every worker and queue slot is occupied."""


class BoundedToolExecutor:
    """A dedicated thread pool with non-blocking, bounded admission.

    Python threads cannot be force-terminated safely.  This class bounds the
    number of running and queued functions; cooperative cancellation is passed
    separately to the function by the caller.
    """

    def __init__(self, *, max_workers: int, max_queue_size: int) -> None:
        if max_workers < 1 or max_queue_size < 0:
            raise ValueError("invalid bounded tool executor capacity")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="itom-assistant-tool",
        )
        self._admission = threading.BoundedSemaphore(max_workers + max_queue_size)

    def submit(self, function: Callable[..., Any], *args: Any) -> Future[Any]:
        if not self._admission.acquire(blocking=False):
            raise ToolExecutorSaturated("assistant tool executor saturated")
        try:
            future = self._executor.submit(function, *args)
        except BaseException:
            self._admission.release()
            raise
        future.add_done_callback(self._release_admission)
        return future

    def _release_admission(self, _future: Future[Any]) -> None:
        self._admission.release()

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
