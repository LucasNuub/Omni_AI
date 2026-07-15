from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import MakeUser


def test_enable_provider_requires_admin(client: TestClient, make_user: MakeUser) -> None:
    _, token = make_user("not-admin@example.com", is_admin=False)

    resp = client.post(
        "/admin/provider/enable",
        json={"provider_name": "groq"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403


def test_enable_provider_requires_auth(client: TestClient) -> None:
    resp = client.post("/admin/provider/enable", json={"provider_name": "groq"})
    assert resp.status_code == 401


def test_disable_then_enable_provider_as_admin(client: TestClient, make_user: MakeUser) -> None:
    _, token = make_user("admin-toggle@example.com", is_admin=True)
    headers = {"Authorization": f"Bearer {token}"}

    disable_resp = client.post(
        "/admin/provider/disable", json={"provider_name": "gemini"}, headers=headers
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json() == {"provider_name": "gemini", "enabled": False}

    enable_resp = client.post(
        "/admin/provider/enable", json={"provider_name": "gemini"}, headers=headers
    )
    assert enable_resp.status_code == 200
    assert enable_resp.json() == {"provider_name": "gemini", "enabled": True}


def test_toggle_unknown_provider_returns_404(client: TestClient, make_user: MakeUser) -> None:
    _, token = make_user("admin-404@example.com", is_admin=True)

    resp = client.post(
        "/admin/provider/enable",
        json={"provider_name": "not-a-real-provider"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404
