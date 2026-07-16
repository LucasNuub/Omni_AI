from __future__ import annotations

from datetime import datetime, timedelta

from app.router.circuit_breaker import CircuitBreaker


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def make_breaker() -> tuple[CircuitBreaker, FakeClock]:
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0))
    breaker = CircuitBreaker(
        base_backoff=timedelta(seconds=10),
        max_backoff=timedelta(seconds=100),
        clock=clock,
    )
    return breaker, clock


def test_provider_available_by_default() -> None:
    breaker, _ = make_breaker()
    assert breaker.is_available("groq") is True


def test_failure_marks_provider_unavailable_until_backoff_passes() -> None:
    breaker, clock = make_breaker()

    breaker.record_failure("groq")
    assert breaker.is_available("groq") is False

    clock.advance(timedelta(seconds=9))
    assert breaker.is_available("groq") is False

    clock.advance(timedelta(seconds=2))  # total 11s > 10s base backoff
    assert breaker.is_available("groq") is True


def test_repeated_failures_double_the_backoff() -> None:
    breaker, clock = make_breaker()

    breaker.record_failure("groq")  # cooldown: 10s, next_backoff -> 20s
    clock.advance(timedelta(seconds=10))
    assert breaker.is_available("groq") is True

    breaker.record_failure("groq")  # cooldown: 20s now, next_backoff -> 40s
    clock.advance(timedelta(seconds=19))
    assert breaker.is_available("groq") is False
    clock.advance(timedelta(seconds=2))
    assert breaker.is_available("groq") is True


def test_backoff_is_capped_at_max_backoff() -> None:
    breaker, clock = make_breaker()

    for _ in range(10):
        breaker.record_failure("groq")
        # skip forward past whatever the current cooldown is
        clock.advance(timedelta(seconds=200))

    breaker.record_failure("groq")
    cooling_until = breaker.cooling_down_until("groq")
    assert cooling_until is not None
    assert cooling_until - clock.now <= timedelta(seconds=100)


def test_success_clears_cooldown_and_resets_backoff() -> None:
    breaker, clock = make_breaker()

    breaker.record_failure("groq")  # next_backoff now 20s
    clock.advance(timedelta(seconds=10))
    assert breaker.is_available("groq") is True

    breaker.record_success("groq")
    assert breaker.cooling_down_until("groq") is None

    # backoff should be back to base (10s), not the doubled 20s
    breaker.record_failure("groq")
    clock.advance(timedelta(seconds=9))
    assert breaker.is_available("groq") is False
    clock.advance(timedelta(seconds=2))
    assert breaker.is_available("groq") is True


def test_independent_providers_have_independent_state() -> None:
    breaker, _ = make_breaker()

    breaker.record_failure("groq")
    assert breaker.is_available("groq") is False
    assert breaker.is_available("gemini") is True
