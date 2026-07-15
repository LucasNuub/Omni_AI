"""Provider onboarding / auto-discovery pipeline — see SPEC.md section 9.

    validate_key -> discover_models -> benchmark -> merge_capabilities -> save

Each step is a separately callable, separately testable function. The
orchestrator (:func:`run_discovery_pipeline`) stops cleanly the moment a
step fails — nothing is saved and ``ProviderKey.status`` is only ever
upgraded on the two terminal outcomes SPEC.md defines: ``invalid_key``
(validate_key returned False) or, on full success, ``active`` +
``health_status = green``. Any other failure (network error, no models
found, ...) leaves the key exactly as it was — still ``pending`` — so a
rescan can simply be retried.

Progress is tracked in-memory (``_PROGRESS``, keyed by ``ProviderKey.id``),
not persisted — SPEC.md sizes this whole system for ~5-15 concurrent users
in a single process, and this mirrors the circuit breaker's same choice in
router/circuit_breaker.py. A server restart mid-scan loses only the
in-flight step detail; the durable pass/fail outcome is still on
``ProviderKey.status``, and rescanning is one click away.
"""

from __future__ import annotations

import enum
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HealthStatus as DbHealthStatus
from app.db.models import Model as ModelRow
from app.db.models import ProviderKey as ProviderKeyRow
from app.db.models import ProviderKeyStatus, QualitySource
from app.providers.base import BenchmarkResult, DiscoveredModel, ProviderAdapter

logger = logging.getLogger(__name__)

DEFAULT_CAPABILITIES_PATH = (
    Path(__file__).resolve().parent.parent / "providers" / "model_capabilities.json"
)


# --- Progress tracking ---------------------------------------------------------------


class DiscoveryStepName(enum.StrEnum):
    verifying_key = "verifying_key"
    discovering_models = "discovering_models"
    benchmarking = "benchmarking"


class DiscoveryStepStatus(enum.StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    failed = "failed"


class DiscoveryOutcome(enum.StrEnum):
    running = "running"
    success = "success"
    invalid_key = "invalid_key"
    error = "error"


@dataclass
class ScanProgress:
    provider_key_id: int
    steps: dict[DiscoveryStepName, DiscoveryStepStatus] = field(default_factory=dict)
    outcome: DiscoveryOutcome = DiscoveryOutcome.running
    models_added: int = 0
    error: str | None = None

    @staticmethod
    def start(provider_key_id: int) -> ScanProgress:
        return ScanProgress(
            provider_key_id=provider_key_id,
            steps=dict.fromkeys(DiscoveryStepName, DiscoveryStepStatus.pending),
        )


_PROGRESS: dict[int, ScanProgress] = {}


def get_progress(provider_key_id: int) -> ScanProgress | None:
    """Poll target for GET /providers/keys/{id}/status."""
    return _PROGRESS.get(provider_key_id)


def _fail(progress: ScanProgress, step: DiscoveryStepName, message: str) -> ScanProgress:
    progress.steps[step] = DiscoveryStepStatus.failed
    progress.outcome = DiscoveryOutcome.error
    progress.error = message
    logger.warning(
        "discovery pipeline for key %d failed at %s: %s", progress.provider_key_id, step, message
    )
    return progress


# --- model_capabilities.json ----------------------------------------------------------


@dataclass(frozen=True)
class FamilySpec:
    family: str
    match_patterns: tuple[str, ...]
    supports_coding_hint: int | None
    supports_reasoning_hint: int | None


@lru_cache(maxsize=8)
def load_model_capabilities(path: Path = DEFAULT_CAPABILITIES_PATH) -> tuple[FamilySpec, ...]:
    """Load and cache the curated family table. Never written to by adapters."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        FamilySpec(
            family=entry["family"],
            match_patterns=tuple(entry["match_patterns"]),
            supports_coding_hint=entry.get("supports_coding_hint"),
            supports_reasoning_hint=entry.get("supports_reasoning_hint"),
        )
        for entry in raw["families"]
    )


def match_family(
    model_id: str, display_name: str, families: Sequence[FamilySpec]
) -> FamilySpec | None:
    """Longest-pattern-wins, case-insensitive substring match against id + display name."""
    haystack = f"{model_id} {display_name}".lower()
    best: FamilySpec | None = None
    best_len = 0
    for family in families:
        for pattern in family.match_patterns:
            needle = pattern.lower()
            if needle in haystack and len(needle) > best_len:
                best = family
                best_len = len(needle)
    return best


# --- merge_capabilities (pure) ---------------------------------------------------------


@dataclass(frozen=True)
class MergedModel:
    model_id: str
    display_name: str
    supports_vision: bool
    context_length: int | None
    speed_rating: int | None
    supports_coding_hint: int | None
    supports_reasoning_hint: int | None
    quality_source: QualitySource


def merge_capabilities(
    discovered: Sequence[DiscoveredModel],
    benchmarks: dict[str, BenchmarkResult],
    families: Sequence[FamilySpec],
) -> list[MergedModel]:
    """Join live-detected fields with the curated family table.

    Pure and I/O-free — no adapter, no DB. ``benchmarks`` is keyed by
    ``model_id``; a model missing from it (outside the benchmark sample) or
    with a failed result just gets ``speed_rating=None``, it still gets
    merged and saved.
    """
    merged: list[MergedModel] = []
    for dm in discovered:
        family = match_family(dm.model_id, dm.display_name, families)
        benchmark = benchmarks.get(dm.model_id)
        speed_rating = benchmark.speed_rating if benchmark and benchmark.success else None

        merged.append(
            MergedModel(
                model_id=dm.model_id,
                display_name=dm.display_name,
                supports_vision=dm.supports_vision,
                context_length=dm.context_length,
                speed_rating=speed_rating,
                supports_coding_hint=family.supports_coding_hint if family else None,
                supports_reasoning_hint=family.supports_reasoning_hint if family else None,
                quality_source=QualitySource.curated if family else QualitySource.unrated,
            )
        )
    return merged


# --- discover / benchmark steps (adapter I/O) -------------------------------------------


async def discover_step(adapter: ProviderAdapter, api_key: str | None) -> list[DiscoveredModel]:
    """Step 2: fetch the live model list. Propagates adapter failures as-is."""
    return await adapter.discover_models(api_key)


async def benchmark_step(
    adapter: ProviderAdapter,
    api_key: str | None,
    models: Sequence[DiscoveredModel],
    sample_size: int,
) -> dict[str, BenchmarkResult]:
    """Step 3: benchmark up to ``sample_size`` discovered models.

    Per-model failures (including timeouts) are soft: ``BenchmarkResult``
    already models them (``success=False``, ``error=...``), so one bad
    model doesn't abort the pipeline — it just gets no ``speed_rating``.
    Models beyond the sample are still saved in step 5, just unbenchmarked.
    """
    results: dict[str, BenchmarkResult] = {}
    for dm in models[:sample_size]:
        try:
            results[dm.model_id] = await adapter.benchmark(dm.model_id, api_key)
        except Exception as exc:  # noqa: BLE001 - one bad model must not sink the pipeline
            results[dm.model_id] = BenchmarkResult(
                model_id=dm.model_id, success=False, error=str(exc)
            )
    return results


# --- save (DB I/O) -----------------------------------------------------------------------


async def save_models(db: AsyncSession, provider_name: str, merged: Sequence[MergedModel]) -> int:
    """Step 5: upsert into ``Model`` by (provider_name, model_id). Caller commits."""
    now = datetime.utcnow()
    for m in merged:
        result = await db.execute(
            select(ModelRow).where(
                ModelRow.provider_name == provider_name, ModelRow.model_id == m.model_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            db.add(
                ModelRow(
                    provider_name=provider_name,
                    model_id=m.model_id,
                    display_name=m.display_name,
                    supports_vision=m.supports_vision,
                    supports_coding_hint=m.supports_coding_hint,
                    supports_reasoning_hint=m.supports_reasoning_hint,
                    context_length=m.context_length,
                    speed_rating=m.speed_rating,
                    free=True,  # SPEC.md section 7: static, all MVP providers are free
                    quality_source=m.quality_source,
                    enabled=True,
                    last_scanned_at=now,
                )
            )
        else:
            existing.display_name = m.display_name
            existing.supports_vision = m.supports_vision
            existing.supports_coding_hint = m.supports_coding_hint
            existing.supports_reasoning_hint = m.supports_reasoning_hint
            existing.context_length = m.context_length
            existing.speed_rating = m.speed_rating
            existing.quality_source = m.quality_source
            existing.last_scanned_at = now
    await db.commit()
    return len(merged)


# --- orchestrator --------------------------------------------------------------------------


async def run_discovery_pipeline(
    db: AsyncSession,
    provider_key: ProviderKeyRow,
    adapter: ProviderAdapter,
    api_key: str | None,
    benchmark_sample_size: int = 10,
) -> ScanProgress:
    """Run the full section 9 pipeline for one ``ProviderKey`` row.

    ``provider_key`` must already be attached to ``db``'s session — this
    function updates its ``status``/``health_status`` in place and commits.
    """
    progress = ScanProgress.start(provider_key.id)
    _PROGRESS[provider_key.id] = progress

    progress.steps[DiscoveryStepName.verifying_key] = DiscoveryStepStatus.in_progress
    try:
        valid = await adapter.validate_key(api_key)
    except Exception as exc:  # noqa: BLE001 - normalized into progress.error
        return _fail(progress, DiscoveryStepName.verifying_key, f"Key validation failed: {exc}")
    if not valid:
        progress.steps[DiscoveryStepName.verifying_key] = DiscoveryStepStatus.failed
        progress.outcome = DiscoveryOutcome.invalid_key
        progress.error = "The provided API key was rejected by the provider."
        provider_key.status = ProviderKeyStatus.invalid_key
        await db.commit()
        return progress
    progress.steps[DiscoveryStepName.verifying_key] = DiscoveryStepStatus.done

    progress.steps[DiscoveryStepName.discovering_models] = DiscoveryStepStatus.in_progress
    try:
        discovered = await discover_step(adapter, api_key)
    except Exception as exc:  # noqa: BLE001 - normalized into progress.error
        return _fail(
            progress, DiscoveryStepName.discovering_models, f"Model discovery failed: {exc}"
        )
    if not discovered:
        return _fail(
            progress,
            DiscoveryStepName.discovering_models,
            "No models were discovered for this key.",
        )
    progress.steps[DiscoveryStepName.discovering_models] = DiscoveryStepStatus.done

    progress.steps[DiscoveryStepName.benchmarking] = DiscoveryStepStatus.in_progress
    benchmarks = await benchmark_step(adapter, api_key, discovered, benchmark_sample_size)
    progress.steps[DiscoveryStepName.benchmarking] = DiscoveryStepStatus.done

    families = load_model_capabilities()
    merged = merge_capabilities(discovered, benchmarks, families)
    saved_count = await save_models(db, provider_key.provider_name, merged)

    provider_key.status = ProviderKeyStatus.active
    provider_key.health_status = DbHealthStatus.green
    await db.commit()

    progress.outcome = DiscoveryOutcome.success
    progress.models_added = saved_count
    return progress
