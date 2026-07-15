from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.router.circuit_breaker import CircuitBreaker
from app.router.engine import AllProvidersExhaustedError, RouteAttempt, RoutingEngine


class DummyProvider:
    """A fake provider whose ``call`` either succeeds or raises, and counts attempts."""

    def __init__(
        self,
        name: str,
        fail_times: int = 0,
        result: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.name = name
        self.model_id = model_id if model_id is not None else f"{name}-model"
        self.fail_times = fail_times
        self.result = result if result is not None else f"{name}-response"
        self.call_count = 0

    async def call(self) -> str:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise RuntimeError(f"{self.name} failed (attempt {self.call_count})")
        return self.result


def attempt_for(provider: DummyProvider) -> RouteAttempt[str]:
    return RouteAttempt(
        provider_name=provider.name, model_id=provider.model_id, invoke=provider.call
    )


async def test_first_healthy_provider_wins() -> None:
    engine = RoutingEngine()
    groq = DummyProvider("groq")
    gemini = DummyProvider("gemini")

    outcome = await engine.route([attempt_for(groq), attempt_for(gemini)])

    assert outcome.result == "groq-response"
    assert outcome.provider_name == "groq"
    assert outcome.model_id == "groq-model"
    assert outcome.attempts == 1
    assert outcome.fallback_count == 0
    assert gemini.call_count == 0


async def test_retries_once_before_falling_back() -> None:
    engine = RoutingEngine(retries_per_provider=1)
    groq = DummyProvider("groq", fail_times=1)  # fails once, then succeeds
    gemini = DummyProvider("gemini")

    outcome = await engine.route([attempt_for(groq), attempt_for(gemini)])

    assert outcome.provider_name == "groq"
    assert groq.call_count == 2
    assert outcome.attempts == 2
    assert outcome.fallback_count == 0
    assert gemini.call_count == 0


async def test_falls_back_to_next_provider_after_exhausting_retries() -> None:
    engine = RoutingEngine(retries_per_provider=1)
    groq = DummyProvider("groq", fail_times=99)  # always fails
    gemini = DummyProvider("gemini")

    outcome = await engine.route([attempt_for(groq), attempt_for(gemini)])

    assert outcome.provider_name == "gemini"
    assert groq.call_count == 2  # 1 initial + 1 retry
    assert gemini.call_count == 1
    assert outcome.fallback_count == 1


async def test_all_providers_exhausted_raises_normalized_error() -> None:
    engine = RoutingEngine(retries_per_provider=0)
    groq = DummyProvider("groq", fail_times=99)
    gemini = DummyProvider("gemini", fail_times=99)

    with pytest.raises(AllProvidersExhaustedError):
        await engine.route([attempt_for(groq), attempt_for(gemini)])


async def test_no_candidates_raises_normalized_error() -> None:
    engine = RoutingEngine()
    with pytest.raises(AllProvidersExhaustedError):
        await engine.route([])


async def test_circuit_breaker_skips_cooling_down_provider() -> None:
    breaker = CircuitBreaker()
    breaker.record_failure("groq")  # groq now cooling down
    engine = RoutingEngine(circuit_breaker=breaker)

    groq = DummyProvider("groq")
    gemini = DummyProvider("gemini")

    outcome = await engine.route([attempt_for(groq), attempt_for(gemini)])

    assert outcome.provider_name == "gemini"
    assert groq.call_count == 0  # never invoked, still cooling down
    assert outcome.fallback_count == 1


async def test_failure_opens_circuit_for_next_route_call() -> None:
    breaker = CircuitBreaker()
    engine = RoutingEngine(circuit_breaker=breaker, retries_per_provider=0)

    groq_bad = DummyProvider("groq", fail_times=99)
    gemini = DummyProvider("gemini")
    await engine.route([attempt_for(groq_bad), attempt_for(gemini)])

    assert breaker.is_available("groq") is False

    # A second, independent routing call should skip groq without invoking it.
    groq_bad_2 = DummyProvider("groq")
    gemini_2 = DummyProvider("gemini")
    outcome = await engine.route([attempt_for(groq_bad_2), attempt_for(gemini_2)])

    assert outcome.provider_name == "gemini"
    assert groq_bad_2.call_count == 0


async def test_retry_success_within_same_call_never_opens_circuit() -> None:
    breaker = CircuitBreaker()
    engine = RoutingEngine(circuit_breaker=breaker, retries_per_provider=1)

    groq = DummyProvider("groq", fail_times=1)  # fails once, then the retry succeeds
    outcome = await engine.route([attempt_for(groq)])

    assert outcome.provider_name == "groq"
    assert outcome.attempts == 2
    assert breaker.is_available("groq") is True
    assert breaker.cooling_down_until("groq") is None


async def test_circuit_reopens_and_clears_after_backoff_and_success() -> None:
    clock_state = {"now": datetime(2026, 1, 1, 12, 0, 0)}

    def clock() -> datetime:
        return clock_state["now"]

    breaker = CircuitBreaker(base_backoff=timedelta(seconds=10), clock=clock)
    engine = RoutingEngine(circuit_breaker=breaker, retries_per_provider=0)

    always_fails = DummyProvider("groq", fail_times=99)
    with pytest.raises(AllProvidersExhaustedError):
        await engine.route([attempt_for(always_fails)])
    assert breaker.is_available("groq") is False

    clock_state["now"] += timedelta(seconds=11)
    assert breaker.is_available("groq") is True

    now_healthy = DummyProvider("groq")
    outcome = await engine.route([attempt_for(now_healthy)])

    assert outcome.provider_name == "groq"
    assert breaker.is_available("groq") is True
    assert breaker.cooling_down_until("groq") is None
