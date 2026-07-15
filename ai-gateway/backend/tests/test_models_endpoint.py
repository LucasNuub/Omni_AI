"""Contract tests for GET /models — SPEC.md sections 7 and 12."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.models import QualitySource
from tests.conftest import MakeUser, SeedModel


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_models_requires_auth(client: TestClient) -> None:
    resp = client.get("/models")
    assert resp.status_code == 401


def test_list_models_returns_saved_model_with_full_shape(
    client: TestClient, make_user: MakeUser, seed_model: SeedModel
) -> None:
    seed_model(
        "groq",
        "shape-test-model",
        display_name="Shape Test Model",
        supports_vision=True,
        supports_coding_hint=4,
        supports_reasoning_hint=3,
        context_length=131072,
        speed_rating=5,
        quality_source=QualitySource.curated,
    )
    _, token = make_user("models-shape@example.com")

    resp = client.get("/models", headers=_auth(token))
    assert resp.status_code == 200

    entry = next(m for m in resp.json() if m["model_id"] == "shape-test-model")
    assert entry["provider_name"] == "groq"
    assert entry["display_name"] == "Shape Test Model"
    assert entry["supports_vision"] is True
    assert entry["supports_coding_hint"] == 4
    assert entry["supports_reasoning_hint"] == 3
    assert entry["context_length"] == 131072
    assert entry["speed_rating"] == 5
    assert entry["free"] is True
    assert entry["quality_source"] == "curated"
    assert entry["enabled"] is True
    assert "id" in entry
    assert "last_scanned_at" in entry


def test_list_models_includes_unrated_models(
    client: TestClient, make_user: MakeUser, seed_model: SeedModel
) -> None:
    seed_model("pollinations", "unrated-test-model")
    _, token = make_user("models-unrated@example.com")

    resp = client.get("/models", headers=_auth(token))

    entry = next(m for m in resp.json() if m["model_id"] == "unrated-test-model")
    assert entry["quality_source"] == "unrated"
    assert entry["supports_coding_hint"] is None


def test_list_models_sorted_by_provider_priority_then_model_id(
    client: TestClient, make_user: MakeUser, seed_model: SeedModel
) -> None:
    # groq (priority 0) sorts before gemini (priority 1) regardless of insert order.
    seed_model("gemini", "sort-test-b")
    seed_model("groq", "sort-test-z")
    seed_model("groq", "sort-test-a")
    _, token = make_user("models-sorted@example.com")

    resp = client.get("/models", headers=_auth(token))
    ids = [m["model_id"] for m in resp.json() if m["model_id"].startswith("sort-test-")]

    assert ids == ["sort-test-a", "sort-test-z", "sort-test-b"]
