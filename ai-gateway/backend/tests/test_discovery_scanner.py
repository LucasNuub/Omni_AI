"""Unit tests for each independently-testable step of discovery/scanner.py.

merge_capabilities is pure (no I/O) and tested directly. discover_step and
benchmark_step are tested against FakeAdapter, no network. The end-to-end
orchestrator (run_discovery_pipeline) and save_models (needs a real DB
session) are covered in test_discovery_pipeline_integration.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.models import QualitySource
from app.discovery.scanner import (
    FamilySpec,
    benchmark_step,
    discover_step,
    load_model_capabilities,
    match_family,
    merge_capabilities,
)
from app.providers.base import BenchmarkResult, DiscoveredModel
from tests.fakes import FakeAdapter, as_adapter

# --- match_family / merge_capabilities (pure) -------------------------------------------

_FAMILIES = (
    FamilySpec(
        family="Llama 3.3",
        match_patterns=("llama-3.3",),
        supports_coding_hint=4,
        supports_reasoning_hint=3,
    ),
    FamilySpec(
        family="Llama 3 (other)",
        match_patterns=("llama-3", "llama"),
        supports_coding_hint=3,
        supports_reasoning_hint=2,
    ),
)


def test_match_family_prefers_longest_pattern() -> None:
    # "llama-3.3-70b-versatile" matches both "llama-3.3" (9 chars) and the
    # generic "llama-3"/"llama" patterns — the more specific one must win.
    family = match_family("llama-3.3-70b-versatile", "Llama 3.3 70b", _FAMILIES)
    assert family is not None
    assert family.family == "Llama 3.3"


def test_match_family_falls_back_to_shorter_pattern() -> None:
    family = match_family("llama-3.1-8b-instant", "Llama 3.1 8b", _FAMILIES)
    assert family is not None
    assert family.family == "Llama 3 (other)"


def test_match_family_returns_none_when_nothing_matches() -> None:
    assert match_family("some-brand-new-model", "Some Brand New Model", _FAMILIES) is None


def test_match_family_matches_case_insensitively() -> None:
    family = match_family("LLAMA-3.3-70B", "Llama 3.3 70B", _FAMILIES)
    assert family is not None
    assert family.family == "Llama 3.3"


def test_merge_capabilities_attaches_curated_hints_on_match() -> None:
    discovered = [
        DiscoveredModel(model_id="llama-3.3-70b", display_name="Llama 3.3 70b", context_length=8192)
    ]
    benchmarks = {
        "llama-3.3-70b": BenchmarkResult(model_id="llama-3.3-70b", success=True, speed_rating=4)
    }

    merged = merge_capabilities(discovered, benchmarks, _FAMILIES)

    assert len(merged) == 1
    assert merged[0].supports_coding_hint == 4
    assert merged[0].supports_reasoning_hint == 3
    assert merged[0].quality_source == QualitySource.curated
    assert merged[0].speed_rating == 4


def test_merge_capabilities_unmatched_model_is_unrated() -> None:
    discovered = [DiscoveredModel(model_id="totally-unknown-model", display_name="Unknown")]

    merged = merge_capabilities(discovered, {}, _FAMILIES)

    assert merged[0].supports_coding_hint is None
    assert merged[0].supports_reasoning_hint is None
    assert merged[0].quality_source == QualitySource.unrated


def test_merge_capabilities_model_outside_benchmark_sample_has_no_speed_rating() -> None:
    discovered = [DiscoveredModel(model_id="llama-3.3-70b", display_name="Llama 3.3 70b")]

    merged = merge_capabilities(discovered, {}, _FAMILIES)  # no benchmark entry at all

    assert merged[0].speed_rating is None
    # still merged/saved — just unbenchmarked, not dropped
    assert merged[0].quality_source == QualitySource.curated


def test_merge_capabilities_failed_benchmark_yields_no_speed_rating() -> None:
    discovered = [DiscoveredModel(model_id="m1", display_name="M1")]
    benchmarks = {"m1": BenchmarkResult(model_id="m1", success=False, error="timeout")}

    merged = merge_capabilities(discovered, benchmarks, _FAMILIES)

    assert merged[0].speed_rating is None


def test_load_model_capabilities_reads_real_seed_file() -> None:
    families = load_model_capabilities()
    assert len(families) >= 15
    assert all(f.match_patterns for f in families)


def test_load_model_capabilities_from_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom_capabilities.json"
    custom.write_text(
        json.dumps(
            {
                "families": [
                    {
                        "family": "Test Family",
                        "match_patterns": ["test-model"],
                        "supports_coding_hint": 1,
                        "supports_reasoning_hint": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    families = load_model_capabilities(custom)

    assert len(families) == 1
    assert families[0].family == "Test Family"


# --- discover_step / benchmark_step (FakeAdapter, no network) ---------------------------


async def test_discover_step_returns_adapters_models() -> None:
    models = [DiscoveredModel(model_id="m1", display_name="M1")]
    adapter = FakeAdapter(name="fake", discovered_models=models)

    result = await discover_step(as_adapter(adapter), "key")

    assert result == models


async def test_discover_step_propagates_adapter_exception() -> None:
    adapter = FakeAdapter(name="fake", discover_raises=True)

    with pytest.raises(RuntimeError):
        await discover_step(as_adapter(adapter), "key")


async def test_benchmark_step_caps_at_sample_size() -> None:
    models = [DiscoveredModel(model_id=f"m{i}", display_name=f"M{i}") for i in range(5)]
    adapter = FakeAdapter(name="fake")

    results = await benchmark_step(as_adapter(adapter), "key", models, sample_size=2)

    assert set(results.keys()) == {"m0", "m1"}


async def test_benchmark_step_records_per_model_timeout_without_raising() -> None:
    models = [
        DiscoveredModel(model_id="good", display_name="Good"),
        DiscoveredModel(model_id="bad", display_name="Bad"),
    ]
    adapter = FakeAdapter(name="fake", benchmark_raises_for=frozenset({"bad"}))

    results = await benchmark_step(as_adapter(adapter), "key", models, sample_size=10)

    assert results["good"].success is True
    assert results["bad"].success is False
    assert "timeout" in (results["bad"].error or "")
