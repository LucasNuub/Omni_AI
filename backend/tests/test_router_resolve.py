"""Tests for the model-level resolution added on top of Phase 1's router.

``resolve()`` is pure (no adapters, no DB, no circuit breaker) so it's
tested directly with plain ``ModelCandidate`` values. ``route_by_model()``
is the resolve-then-route convenience entry point chat.py is expected to
adopt; it's tested with dummy invoke factories, same style as
test_router_engine.py's provider-level tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.router.circuit_breaker import CircuitBreaker
from app.router.engine import ModelCandidate, RoutingEngine, RoutingProfile


def _candidate(
    provider_name: str,
    model_id: str,
    priority: int = 0,
    speed: int | None = None,
    vision: bool = False,
    coding: int | None = None,
    reasoning: int | None = None,
) -> ModelCandidate:
    return ModelCandidate(
        provider_name=provider_name,
        provider_priority=priority,
        model_id=model_id,
        speed_rating=speed,
        supports_vision=vision,
        supports_coding_hint=coding,
        supports_reasoning_hint=reasoning,
    )


# --- resolve(): balanced -------------------------------------------------------------


def test_balanced_orders_by_provider_priority_then_model_id() -> None:
    candidates = [
        _candidate("gemini", "g-model", priority=1),
        _candidate("groq", "z-model", priority=0),
        _candidate("groq", "a-model", priority=0),
    ]

    resolved = RoutingEngine.resolve(candidates, profile=RoutingProfile.balanced)

    assert [(c.provider_name, c.model_id) for c in resolved] == [
        ("groq", "a-model"),
        ("groq", "z-model"),
        ("gemini", "g-model"),
    ]


def test_balanced_is_the_default_profile() -> None:
    candidates = [_candidate("gemini", "m", priority=1), _candidate("groq", "m", priority=0)]

    resolved = RoutingEngine.resolve(candidates)

    assert resolved[0].provider_name == "groq"


# --- resolve(): fast -------------------------------------------------------------------


def test_fast_orders_by_speed_rating_descending_unbenchmarked_last() -> None:
    candidates = [
        _candidate("a", "m1", speed=2),
        _candidate("b", "m2", speed=5),
        _candidate("c", "m3", speed=None),
        _candidate("d", "m4", speed=4),
    ]

    resolved = RoutingEngine.resolve(candidates, profile=RoutingProfile.fast)

    assert [c.model_id for c in resolved] == ["m2", "m4", "m1", "m3"]


# --- resolve(): best_quality -------------------------------------------------------------


def test_best_quality_ranks_by_required_capability() -> None:
    candidates = [
        _candidate("a", "m1", coding=3, reasoning=5),
        _candidate("b", "m2", coding=5, reasoning=2),
    ]

    by_coding = RoutingEngine.resolve(
        candidates, profile=RoutingProfile.best_quality, required_capability="coding"
    )
    assert [c.model_id for c in by_coding] == ["m2", "m1"]

    by_reasoning = RoutingEngine.resolve(
        candidates, profile=RoutingProfile.best_quality, required_capability="reasoning"
    )
    assert [c.model_id for c in by_reasoning] == ["m1", "m2"]


def test_best_quality_without_capability_uses_combined_coding_and_reasoning() -> None:
    candidates = [
        _candidate("a", "m1", coding=3, reasoning=1),  # combined 4
        _candidate("b", "m2", coding=2, reasoning=4),  # combined 6
    ]

    resolved = RoutingEngine.resolve(candidates, profile=RoutingProfile.best_quality)

    assert [c.model_id for c in resolved] == ["m2", "m1"]


def test_best_quality_vision_ranks_vision_capable_models_first() -> None:
    candidates = [
        _candidate("a", "no-vision", vision=False, coding=5, reasoning=5),
        _candidate("b", "has-vision", vision=True, coding=1, reasoning=1),
    ]

    resolved = RoutingEngine.resolve(
        candidates, profile=RoutingProfile.best_quality, required_capability="vision"
    )

    assert resolved[0].model_id == "has-vision"


# --- resolve(): capability filtering (applies to every profile) ------------------------


def test_capability_filter_excludes_non_vision_models() -> None:
    candidates = [
        _candidate("a", "vision-model", vision=True),
        _candidate("b", "text-model", vision=False),
    ]

    resolved = RoutingEngine.resolve(candidates, required_capability="vision")

    assert [c.model_id for c in resolved] == ["vision-model"]


def test_capability_filter_for_coding_requires_a_rating_not_none() -> None:
    candidates = [
        _candidate("a", "rated", coding=1),
        _candidate("b", "unrated", coding=None),
    ]

    resolved = RoutingEngine.resolve(candidates, required_capability="coding")

    assert [c.model_id for c in resolved] == ["rated"]


def test_no_matching_candidates_returns_empty_list() -> None:
    candidates = [_candidate("a", "text-model", vision=False)]

    resolved = RoutingEngine.resolve(candidates, required_capability="vision")

    assert resolved == []


# --- route_by_model(): resolve() + route() together -------------------------------------


async def test_route_by_model_resolves_then_routes() -> None:
    engine = RoutingEngine()
    candidates = [
        _candidate("groq", "m-groq", priority=0),
        _candidate("gemini", "m-gemini", priority=1),
    ]
    calls: list[str] = []

    def make_invoke(c: ModelCandidate) -> Callable[[], Awaitable[str]]:
        async def _invoke() -> str:
            calls.append(c.model_id)
            return f"{c.provider_name}:{c.model_id}"

        return _invoke

    outcome = await engine.route_by_model(candidates, make_invoke)

    assert outcome.provider_name == "groq"
    assert outcome.model_id == "m-groq"
    assert outcome.result == "groq:m-groq"
    assert calls == ["m-groq"]


async def test_route_by_model_falls_back_across_models_and_providers() -> None:
    engine = RoutingEngine(retries_per_provider=0)
    candidates = [
        _candidate("groq", "m-groq", priority=0),
        _candidate("gemini", "m-gemini", priority=1),
    ]

    def make_invoke(c: ModelCandidate) -> Callable[[], Awaitable[str]]:
        async def _invoke() -> str:
            if c.provider_name == "groq":
                raise RuntimeError("groq down")
            return "ok"

        return _invoke

    outcome = await engine.route_by_model(candidates, make_invoke)

    assert outcome.provider_name == "gemini"
    assert outcome.model_id == "m-gemini"


async def test_circuit_breaker_stays_provider_keyed_across_models() -> None:
    """A model exhausting retries cools down the whole provider, not just itself."""
    breaker = CircuitBreaker()
    engine = RoutingEngine(circuit_breaker=breaker, retries_per_provider=0)

    candidates = [
        _candidate("groq", "m1", priority=0),
        _candidate("groq", "m2", priority=0),
        _candidate("gemini", "m3", priority=1),
    ]
    called: list[str] = []

    def make_invoke(c: ModelCandidate) -> Callable[[], Awaitable[str]]:
        async def _invoke() -> str:
            called.append(c.model_id)
            if c.provider_name == "groq":
                raise RuntimeError("groq down")
            return "ok"

        return _invoke

    outcome = await engine.route_by_model(candidates, make_invoke)

    assert outcome.provider_name == "gemini"
    # m2 must never be tried: once m1 exhausts retries it opens the circuit
    # for the whole "groq" provider, and route() skips m2 as a result.
    assert called == ["m1", "m3"]
    assert breaker.is_available("groq") is False
