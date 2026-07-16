from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.providers.registry import ADAPTERS
from tests.conftest import MakeUser, OnlyProvidersEnabled
from tests.fakes import FakeAdapter


def test_health_no_auth_required(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/status")
    assert resp.status_code == 401


def test_status_reports_healthy_provider_with_quota(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"groq"})
    fake = FakeAdapter(name="groq", healthy=True, quota_remaining=42, quota_limit=100)
    monkeypatch.setitem(ADAPTERS, "groq", fake)

    _, token = make_user("status-healthy@example.com")
    resp = client.get("/status", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json() == {
        "groq": {
            "healthy": True,
            "remaining_today": 42,
            "limit": 100,
            "reset_at": None,
            "status": "green",
            "cooling_down_until": None,
        }
    }


def test_status_reports_unhealthy_provider(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_providers_enabled({"groq"})
    monkeypatch.setitem(ADAPTERS, "groq", FakeAdapter(name="groq", healthy=False))

    _, token = make_user("status-unhealthy@example.com")
    resp = client.get("/status", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()["groq"]
    assert body["healthy"] is False
    # Unhealthy always buckets to the red traffic-light, regardless of quota.
    assert body["status"] == "red"


def test_status_excludes_disabled_providers(
    client: TestClient,
    make_user: MakeUser,
    only_providers_enabled: OnlyProvidersEnabled,
) -> None:
    only_providers_enabled(set())  # every provider disabled

    _, token = make_user("status-disabled@example.com")
    resp = client.get("/status", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json() == {}
