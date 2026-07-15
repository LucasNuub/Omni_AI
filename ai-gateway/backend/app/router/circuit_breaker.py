"""Lazy circuit breaker — see SPEC.md section 8.

No background polling: a provider is only checked against its cooldown
timestamp when a request actually wants to use it. A failed request sets
``cooling_down_until``; the next request just skips that provider until the
deadline passes, then tries again and either clears the cooldown (success)
or doubles the backoff (failure again). Costs zero quota when nobody's using
the app.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

DEFAULT_BASE_BACKOFF = timedelta(seconds=5)
DEFAULT_MAX_BACKOFF = timedelta(minutes=10)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _ProviderState:
    next_backoff: timedelta
    cooling_down_until: datetime | None = None


@dataclass
class CircuitBreaker:
    base_backoff: timedelta = DEFAULT_BASE_BACKOFF
    max_backoff: timedelta = DEFAULT_MAX_BACKOFF
    clock: Callable[[], datetime] = field(default=_utcnow)

    _state: dict[str, _ProviderState] = field(default_factory=dict, init=False, repr=False)

    def is_available(self, provider_name: str) -> bool:
        """True if this provider is not currently cooling down."""
        state = self._state.get(provider_name)
        if state is None or state.cooling_down_until is None:
            return True
        return self.clock() >= state.cooling_down_until

    def record_success(self, provider_name: str) -> None:
        """Clear any cooldown and reset backoff to the base value."""
        self._state.pop(provider_name, None)

    def record_failure(self, provider_name: str) -> None:
        """Start (or extend) a cooldown, doubling the backoff for next time."""
        state = self._state.setdefault(
            provider_name, _ProviderState(next_backoff=self.base_backoff)
        )
        state.cooling_down_until = self.clock() + state.next_backoff
        state.next_backoff = min(state.next_backoff * 2, self.max_backoff)

    def cooling_down_until(self, provider_name: str) -> datetime | None:
        state = self._state.get(provider_name)
        return state.cooling_down_until if state else None
