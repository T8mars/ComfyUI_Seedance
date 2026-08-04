"""Thread-local runtime controls used by optional concurrent nodes."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional


class ConcurrentTaskCancelled(RuntimeError):
    """Raised when a local concurrent task is cancelled."""


_runtime_local = threading.local()


@contextmanager
def concurrent_worker_context(
    cancel_event: threading.Event,
    progress_callback: Optional[Callable[[float, float], None]] = None,
) -> Iterator[None]:
    previous_event = getattr(_runtime_local, "cancel_event", None)
    previous_suppression = getattr(_runtime_local, "suppress_progress", False)
    previous_callback = getattr(_runtime_local, "progress_callback", None)
    _runtime_local.cancel_event = cancel_event
    _runtime_local.suppress_progress = True
    _runtime_local.progress_callback = progress_callback
    try:
        yield
    finally:
        _runtime_local.cancel_event = previous_event
        _runtime_local.suppress_progress = previous_suppression
        _runtime_local.progress_callback = previous_callback


def current_cancel_event() -> Optional[threading.Event]:
    return getattr(_runtime_local, "cancel_event", None)


def progress_is_suppressed() -> bool:
    return bool(getattr(_runtime_local, "suppress_progress", False))


def current_progress_callback() -> Optional[Callable[[float, float], None]]:
    return getattr(_runtime_local, "progress_callback", None)


def check_cancelled() -> None:
    event = current_cancel_event()
    if event is not None and event.is_set():
        raise ConcurrentTaskCancelled("Concurrent task cancelled locally.")


def cooperative_sleep(seconds: float) -> None:
    delay = max(0.0, float(seconds))
    event = current_cancel_event()
    if event is None:
        time.sleep(delay)
        return
    if event.wait(delay):
        raise ConcurrentTaskCancelled("Concurrent task cancelled locally.")
