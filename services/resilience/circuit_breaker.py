"""Circuit Breaker pattern for external banking integrations and LLM resilience."""

import time
from enum import Enum
from typing import Callable, Any, Optional
import structlog

logger = structlog.get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: traffic flows through
    OPEN = "OPEN"            # Tripped: immediate fail-fast without calling external service
    HALF_OPEN = "HALF_OPEN"  # Trial state: testing if downstream service has recovered


class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        half_open_success_threshold: int = 2
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None

    async def call(self, async_func: Callable, *args, **kwargs) -> Any:
        """Executes an async function with circuit breaker protection."""
        now = time.time()

        # 1. Evaluate state transitions
        if self.state == CircuitState.OPEN:
            if self.last_failure_time and (now - self.last_failure_time) >= self.recovery_timeout_seconds:
                logger.info("Circuit breaker transitioning to HALF_OPEN", circuit=self.name)
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
            else:
                logger.warn("Circuit breaker OPEN: failing fast", circuit=self.name)
                raise CircuitBreakerOpenException(
                    f"Downstream service '{self.name}' is currently unavailable (circuit OPEN)."
                )

        # 2. Attempt execution
        try:
            result = await async_func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            raise exc

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_success_threshold:
                logger.info("Circuit breaker recovered: transitioning to CLOSED", circuit=self.name)
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
        else:
            self.failure_count = 0

    def _on_failure(self, exc: Exception):
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warn(
            "Service call failed",
            circuit=self.name,
            failure_count=self.failure_count,
            threshold=self.failure_threshold,
            error=str(exc)
        )

        if self.state in [CircuitState.CLOSED, CircuitState.HALF_OPEN]:
            if self.failure_count >= self.failure_threshold:
                logger.error("Circuit breaker tripped to OPEN", circuit=self.name)
                self.state = CircuitState.OPEN

