from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from incidentzero.model.errors import PermanentModelError, TransientModelError

T = TypeVar("T")


class RetryPolicy:
    def __init__(self, max_attempts: int = 3, sleeper: Callable[[float], None] = time.sleep) -> None:
        self.max_attempts = max_attempts
        self.sleeper = sleeper

    def call_model(self, fn: Callable[[], T]) -> T:
        """Retry only transient provider/network errors, with capped exponential backoff."""
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn()
            except TransientModelError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                delay = min(0.5 * (2 ** (attempt - 1)), 2.0)
                self.sleeper(delay)
            except PermanentModelError:
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("RetryPolicy.call_model exhausted without a model error")
