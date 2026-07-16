"""Routing engine — see SPEC.md section 8.

Resolution now happens at the **model** level via the Model Registry, not
just provider level: three profiles (Fast / Balanced / Best quality) rank
an arbitrary set of candidate models, capability-aware when the caller
knows the request needs vision/coding/reasoning. Execution (retry once,
then fall back to the next model — which may switch providers entirely)
is unchanged in spirit from Phase 1, just keyed by (provider_name,
model_id) pairs instead of provider_name alone.

The circuit breaker stays **provider**-keyed, per spec: a failing model
still cools down its whole provider, not just that one model, since
quota/outage problems are provider-wide.

This package stays DB-free on purpose (SPEC.md's Phase 1 testing
philosophy: routing is tested against fake/dummy providers, not real
ones). ``ModelCandidate`` is a plain snapshot the caller builds from
``Model``/``Provider`` rows — callers translate between ORM rows and this
DTO at the boundary, same pattern as ``providers/base.py``'s DTOs.

New call shape for callers (e.g. app/api/chat.py):

    candidates = [ModelCandidate(...), ...]          # from Model Registry rows
    outcome = await engine.route_by_model(
        candidates,
        make_invoke=lambda c: build_invoke_for(c),    # ModelCandidate -> () -> Awaitable[T]
        profile=RoutingProfile.balanced,
        required_capability="vision",                 # or None
    )
    outcome.provider_name, outcome.model_id, outcome.result

``route_by_model`` is ``resolve()`` (pure ranking) followed by ``route()``
(execution). Both remain independently usable: ``resolve()`` needs no
adapters/network and is trivially unit-testable; ``route()`` is the same
generic retry/fallback/circuit-breaker executor as before, just operating
on ``RouteAttempt`` objects that now carry a ``model_id`` alongside
``provider_name``. This is the breaking change: ``RouteAttempt`` and
``RouteOutcome`` both gained a required ``model_id`` field, so any
existing caller built against the Phase 1 provider-only ``RouteAttempt``
must add one.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.router.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class AllProvidersExhaustedError(Exception):
    """Normalized error surfaced to the client when every candidate fails."""


@dataclass(frozen=True)
class RouteAttempt[T]:
    provider_name: str
    model_id: str
    invoke: Callable[[], Awaitable[T]]


@dataclass(frozen=True)
class RouteOutcome[T]:
    result: T
    provider_name: str
    model_id: str
    attempts: int
    fallback_count: int


class RoutingProfile(enum.StrEnum):
    fast = "fast"
    balanced = "balanced"
    best_quality = "best_quality"


RequiredCapability = Literal["vision", "coding", "reasoning"]


@dataclass(frozen=True)
class ModelCandidate:
    """DB-free snapshot of one Model Registry row (a ``Model`` joined with its
    ``Provider``), enough to rank and route on without a session.
    """

    provider_name: str
    provider_priority: int
    model_id: str
    speed_rating: int | None = None
    supports_vision: bool = False
    supports_coding_hint: int | None = None
    supports_reasoning_hint: int | None = None


def _matches_capability(candidate: ModelCandidate, required: RequiredCapability | None) -> bool:
    if required is None:
        return True
    if required == "vision":
        return candidate.supports_vision
    if required == "coding":
        return candidate.supports_coding_hint is not None
    return candidate.supports_reasoning_hint is not None


def _quality_score(candidate: ModelCandidate, required: RequiredCapability | None) -> float:
    if required == "vision":
        return 1.0 if candidate.supports_vision else 0.0
    if required == "coding":
        return float(candidate.supports_coding_hint or 0)
    if required == "reasoning":
        return float(candidate.supports_reasoning_hint or 0)
    # No specific capability requested: use combined coding+reasoning as a
    # general quality proxy — SPEC.md doesn't define "best" for this case.
    coding = float(candidate.supports_coding_hint or 0)
    reasoning = float(candidate.supports_reasoning_hint or 0)
    return coding + reasoning


class RoutingEngine:
    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        retries_per_provider: int = 1,
    ) -> None:
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.retries_per_provider = retries_per_provider

    @staticmethod
    def resolve(
        candidates: Sequence[ModelCandidate],
        profile: RoutingProfile = RoutingProfile.balanced,
        required_capability: RequiredCapability | None = None,
    ) -> list[ModelCandidate]:
        """Order ``candidates`` per SPEC.md section 8's three profiles.

        Pure and I/O-free — this only ranks whatever's handed to it; the
        caller is responsible for only passing *enabled* models. Health
        filtering (skipping providers currently cooling down) is deliberately
        NOT done here: ``route()`` already skips those as it walks the
        ordered list, which is functionally equivalent to filtering them out
        up front and keeps this method testable without a circuit breaker.
        """
        pool = [c for c in candidates if _matches_capability(c, required_capability)]

        if profile == RoutingProfile.fast:
            # "Lowest latency" == highest speed_rating (1-5 stars, 5 fastest);
            # unbenchmarked (None) models sort last.
            return sorted(pool, key=lambda c: (c.speed_rating is None, -(c.speed_rating or 0)))

        if profile == RoutingProfile.best_quality:
            return sorted(pool, key=lambda c: -_quality_score(c, required_capability))

        # balanced (default): priority-ordered list, first match wins.
        return sorted(pool, key=lambda c: (c.provider_priority, c.model_id))

    async def route[T](self, candidates: Sequence[RouteAttempt[T]]) -> RouteOutcome[T]:
        """Try ``candidates`` in order, skipping cooling-down providers.

        Each provider gets ``1 + retries_per_provider`` attempts before the
        engine falls back to the next one in the chain. The circuit breaker
        is keyed by ``provider_name`` only — a model that exhausts its
        retries cools down its whole provider, not just that model.
        """
        if not candidates:
            raise AllProvidersExhaustedError("No providers configured.")

        fallback_count = 0
        total_attempts = 0
        last_error: Exception | None = None

        for candidate in candidates:
            if not self.circuit_breaker.is_available(candidate.provider_name):
                logger.info("skipping %s: cooling down", candidate.provider_name)
                fallback_count += 1
                continue

            for attempt_num in range(1 + self.retries_per_provider):
                total_attempts += 1
                try:
                    result = await candidate.invoke()
                except Exception as exc:  # noqa: BLE001 - normalized at the boundary
                    last_error = exc
                    logger.warning(
                        "provider %s model %s attempt %d failed: %s",
                        candidate.provider_name,
                        candidate.model_id,
                        attempt_num + 1,
                        exc,
                    )
                    continue
                else:
                    self.circuit_breaker.record_success(candidate.provider_name)
                    return RouteOutcome(
                        result=result,
                        provider_name=candidate.provider_name,
                        model_id=candidate.model_id,
                        attempts=total_attempts,
                        fallback_count=fallback_count,
                    )

            self.circuit_breaker.record_failure(candidate.provider_name)
            fallback_count += 1

        raise AllProvidersExhaustedError(
            "All providers are currently unavailable. Please try again shortly."
        ) from last_error

    async def route_by_model[T](
        self,
        candidates: Sequence[ModelCandidate],
        make_invoke: Callable[[ModelCandidate], Callable[[], Awaitable[T]]],
        *,
        profile: RoutingProfile = RoutingProfile.balanced,
        required_capability: RequiredCapability | None = None,
    ) -> RouteOutcome[T]:
        """Convenience entry point: ``resolve()`` then ``route()`` in one call.

        ``make_invoke`` turns a resolved ``ModelCandidate`` into the
        zero-arg callable ``route()`` needs — typically closing over the
        adapter instance, messages, and a resolved API key. Building that
        callable requires provider/DB knowledge this package doesn't have,
        so it stays the caller's responsibility.
        """
        resolved = self.resolve(
            candidates, profile=profile, required_capability=required_capability
        )
        attempts = [
            RouteAttempt(
                provider_name=c.provider_name, model_id=c.model_id, invoke=make_invoke(c)
            )
            for c in resolved
        ]
        return await self.route(attempts)
