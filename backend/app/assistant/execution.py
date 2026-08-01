"""Bounded admission for synchronous assistant capability workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from concurrent.futures import Future, ThreadPoolExecutor
import threading
import time
from typing import Any, Callable

from app.core.config import settings


class ToolExecutorSaturated(RuntimeError):
    """Raised before submission when every worker and queue slot is occupied."""


class BoundedExecutionTimeout(TimeoutError):
    """Raised when a bounded worker call exhausts its caller-owned deadline."""


class BoundedExecutorReservation:
    """One idempotently releasable admission slot reserved before other work."""

    def __init__(self, owner: "BoundedToolExecutor") -> None:
        self._owner = owner
        self._state = "reserved"
        self._lock = threading.Lock()

    def submit(self, function: Callable[..., Any], *args: Any) -> Future[Any]:
        with self._lock:
            if self._state != "reserved":
                raise RuntimeError("assistant executor reservation is not available")
            self._state = "submitted"
        try:
            future = self._owner._executor.submit(function, *args)
        except BaseException:
            with self._lock:
                self._state = "released"
            self._owner._release_admission()
            raise
        future.add_done_callback(self._submitted_done)
        return future

    def release(self) -> None:
        with self._lock:
            if self._state != "reserved":
                return
            self._state = "released"
        self._owner._release_admission()

    def _submitted_done(self, _future: Future[Any]) -> None:
        with self._lock:
            if self._state == "released":
                return
            self._state = "released"
        self._owner._release_admission()


class BoundedToolExecutor:
    """A dedicated thread pool with non-blocking, bounded admission.

    Python threads cannot be force-terminated safely.  This class bounds the
    number of running and queued functions; cooperative cancellation is passed
    separately to the function by the caller.
    """

    def __init__(
        self,
        *,
        max_workers: int,
        max_queue_size: int,
        thread_name_prefix: str = "itom-assistant-tool",
    ) -> None:
        if max_workers < 1 or max_queue_size < 0:
            raise ValueError("invalid bounded tool executor capacity")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._admission = threading.BoundedSemaphore(max_workers + max_queue_size)

    def reserve(self) -> BoundedExecutorReservation:
        if not self._admission.acquire(blocking=False):
            raise ToolExecutorSaturated("assistant executor saturated")
        return BoundedExecutorReservation(self)

    def submit(self, function: Callable[..., Any], *args: Any) -> Future[Any]:
        return self.reserve().submit(function, *args)

    def _release_admission(self) -> None:
        self._admission.release()

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)


async def await_bounded_call(
    executor: BoundedToolExecutor,
    function: Callable[..., Any],
    *args: Any,
    deadline_monotonic: float,
    disconnect_check: Callable[[], Awaitable[bool]] | None = None,
    cancel: Callable[[], None] | None = None,
    poll_seconds: float = 0.025,
) -> Any:
    """Await one admitted synchronous call without using asyncio's default pool."""
    if deadline_monotonic <= time.monotonic():
        if cancel is not None:
            cancel()
        raise BoundedExecutionTimeout("assistant bounded call deadline exhausted")
    reservation = executor.reserve()
    try:
        concurrent_future = reservation.submit(function, *args)
    except BaseException:
        reservation.release()
        raise
    task = asyncio.wrap_future(concurrent_future)
    try:
        while True:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                if cancel is not None:
                    cancel()
                raise BoundedExecutionTimeout("assistant bounded call deadline exhausted")
            done, _pending = await asyncio.wait(
                {task}, timeout=min(max(0.001, poll_seconds), remaining),
            )
            if task in done:
                return task.result()
            if disconnect_check is not None and await disconnect_check():
                if cancel is not None:
                    cancel()
                raise asyncio.CancelledError()
    except BaseException:
        if cancel is not None:
            cancel()
        raise


DEFAULT_ASSISTANT_DB_EXECUTOR = BoundedToolExecutor(
    max_workers=settings.ai_assistant_tool_executor_workers,
    max_queue_size=settings.ai_assistant_tool_executor_queue_size,
    thread_name_prefix="itom-assistant-db",
)
