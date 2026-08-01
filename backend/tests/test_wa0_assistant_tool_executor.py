"""WA0 bounded worker admission and cooperative cancellation contracts."""

import threading
import time

import pytest

from app.assistant.execution import BoundedToolExecutor, ToolExecutorSaturated
from app.assistant.types import CapabilityExecutionCancelled, CapabilityExecutionContext


def test_saturated_executor_rejects_before_worker_can_create_session():
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0)
    release = threading.Event()
    started = threading.Event()
    sessions_created = 0

    def occupying_worker():
        started.set()
        release.wait(timeout=1)

    def would_create_session():
        nonlocal sessions_created
        sessions_created += 1

    first = executor.submit(occupying_worker)
    assert started.wait(timeout=0.5)
    try:
        with pytest.raises(ToolExecutorSaturated):
            executor.submit(would_create_session)
        assert sessions_created == 0
    finally:
        release.set()
        first.result(timeout=1)
        executor.shutdown(wait=True)


def test_reserved_admission_can_be_released_without_submitting_work():
    """Validation failures must return reserved capacity without creating a worker."""
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0)
    reservation = executor.reserve()
    with pytest.raises(ToolExecutorSaturated):
        executor.reserve()

    reservation.release()
    next_reservation = executor.reserve()
    next_reservation.release()
    executor.shutdown(wait=True)


def test_reserved_admission_is_released_after_submitted_work_finishes():
    """A submitted reservation remains occupied until its future is terminal."""
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0)
    release = threading.Event()
    started = threading.Event()

    def worker():
        started.set()
        release.wait(timeout=1)
        return "finished"

    reservation = executor.reserve()
    future = reservation.submit(worker)
    assert started.wait(timeout=0.5)
    with pytest.raises(ToolExecutorSaturated):
        executor.reserve()
    release.set()
    assert future.result(timeout=1) == "finished"

    next_reservation = executor.reserve()
    next_reservation.release()
    executor.shutdown(wait=True)


def test_cooperative_context_interrupts_worker_without_blocking_event_loop_contract():
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0)
    context = CapabilityExecutionContext(deadline_monotonic=time.monotonic() + 1)
    started = threading.Event()
    observed = threading.Event()

    def cooperative_worker():
        started.set()
        while not context.is_cancelled():
            time.sleep(0.005)
        observed.set()
        context.raise_if_cancelled()

    future = executor.submit(cooperative_worker)
    assert started.wait(timeout=0.5)
    context.cancel()
    assert observed.wait(timeout=0.5)
    with pytest.raises(CapabilityExecutionCancelled):
        future.result(timeout=1)
    executor.shutdown(wait=True)


def test_non_cooperative_background_worker_still_runs_finally_and_closes_session():
    executor = BoundedToolExecutor(max_workers=1, max_queue_size=0)
    context = CapabilityExecutionContext(deadline_monotonic=time.monotonic() + 0.02)
    release = threading.Event()
    started = threading.Event()
    closed = threading.Event()

    class FakeSession:
        def rollback(self):
            return None

        def close(self):
            closed.set()

    def non_cooperative_worker():
        session = FakeSession()
        try:
            started.set()
            release.wait(timeout=1)
        finally:
            session.rollback()
            session.close()

    future = executor.submit(non_cooperative_worker)
    assert started.wait(timeout=0.5)
    context.cancel()
    assert not closed.is_set()
    release.set()
    future.result(timeout=1)
    assert closed.is_set()
    executor.shutdown(wait=True)
