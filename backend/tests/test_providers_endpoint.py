"""Contract tests for POST/GET/DELETE /providers/keys and the status/rescan
polling endpoints — SPEC.md sections 9, 10, 12.

``ADAPTERS[provider_name]`` is monkeypatched with a ``FakeAdapter`` so
POST/rescan (which run discovery/scanner.py as a FastAPI background task —
TestClient executes it synchronously before the response returns) never
make a real network call. Real-adapter behavior is covered separately in
test_discovery_pipeline_integration.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.providers import mask_key
from app.providers.base import DiscoveredModel
from app.providers.registry import ADAPTERS
from tests.conftest import MakeUser
from tests.fakes import FakeAdapter


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _no_op_adapter(name: str) -> FakeAdapter:
    """A FakeAdapter that discovers nothing — enough to exercise auth/CRUD
    plumbing in tests that don't care about the discovery outcome."""
    return FakeAdapter(name=name, auth_type="api_key", discovered_models=[])


# --- mask_key (pure) -------------------------------------------------------------------


def test_mask_key_keeps_prefix_and_last_four() -> None:
    assert mask_key("sk-abcdefghijklmnop") == "sk-...mnop"


def test_mask_key_handles_short_strings() -> None:
    assert mask_key("short") == "***"


# --- POST /providers/keys ---------------------------------------------------------------


def test_add_provider_key_requires_auth(client: TestClient) -> None:
    resp = client.post("/providers/keys", json={"provider_name": "groq", "api_key": "sk-x"})
    assert resp.status_code == 401


def test_add_provider_key_unknown_provider_returns_404(
    client: TestClient, make_user: MakeUser
) -> None:
    _, token = make_user("providers-404@example.com")
    resp = client.post(
        "/providers/keys",
        json={"provider_name": "not-a-real-provider", "api_key": "sk-x"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_add_shared_provider_key_requires_admin(
    client: TestClient, make_user: MakeUser
) -> None:
    _, token = make_user("providers-notadmin@example.com")
    resp = client.post(
        "/providers/keys",
        json={"provider_name": "groq", "api_key": "sk-x", "is_shared": True},
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_add_provider_key_runs_discovery_and_reaches_success(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        ADAPTERS,
        "groq",
        FakeAdapter(
            name="groq",
            auth_type="api_key",
            discovered_models=[
                DiscoveredModel(model_id="llama-3.3-70b-versatile", display_name="Llama 3.3 70b")
            ],
        ),
    )
    _, token = make_user("providers-success@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "groq", "api_key": "sk-real", "nickname": "my key"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["provider_name"] == "groq"
    assert body["nickname"] == "my key"
    assert body["masked_key"] == mask_key("sk-real")
    assert body["is_shared"] is False
    key_id = body["id"]

    # TestClient runs BackgroundTasks synchronously before returning, so the
    # discovery pipeline (against the FakeAdapter) has already finished here.
    status_resp = client.get(f"/providers/keys/{key_id}/status", headers=_auth(token))
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["outcome"] == "success"
    assert status_body["models_added"] == 1
    assert status_body["steps"] == {
        "verifying_key": "done",
        "discovering_models": "done",
        "benchmarking": "done",
    }


def test_add_provider_key_no_models_found_reaches_error_outcome(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "gemini", _no_op_adapter("gemini"))
    _, token = make_user("providers-nomodels@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "gemini", "api_key": "sk-real"},
        headers=_auth(token),
    )
    key_id = create_resp.json()["id"]

    status_resp = client.get(f"/providers/keys/{key_id}/status", headers=_auth(token))
    body = status_resp.json()
    assert body["outcome"] == "error"
    assert body["error"] is not None


def test_add_provider_key_invalid_key_reaches_invalid_key_outcome(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        ADAPTERS,
        "openrouter",
        FakeAdapter(name="openrouter", auth_type="api_key", validate_key_result=False),
    )
    _, token = make_user("providers-invalidkey@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "openrouter", "api_key": "sk-bad"},
        headers=_auth(token),
    )
    key_id = create_resp.json()["id"]

    status_resp = client.get(f"/providers/keys/{key_id}/status", headers=_auth(token))
    body = status_resp.json()
    assert body["outcome"] == "invalid_key"

    list_resp = client.get("/providers/keys", headers=_auth(token))
    entry = next(k for k in list_resp.json() if k["id"] == key_id)
    assert entry["status"] == "invalid_key"


# --- GET /providers/keys ---------------------------------------------------------------


def test_list_provider_keys_shows_own_and_shared_but_not_others_personal(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "deepseek", _no_op_adapter("deepseek"))
    _, admin_token = make_user("providers-list-admin@example.com", is_admin=True)
    _, user_a_token = make_user("providers-list-a@example.com")
    _, user_b_token = make_user("providers-list-b@example.com")

    shared_resp = client.post(
        "/providers/keys",
        json={"provider_name": "deepseek", "api_key": "sk-shared", "is_shared": True},
        headers=_auth(admin_token),
    )
    assert shared_resp.status_code == 201

    own_resp = client.post(
        "/providers/keys",
        json={"provider_name": "deepseek", "api_key": "sk-personal-a"},
        headers=_auth(user_a_token),
    )
    assert own_resp.status_code == 201

    listing = client.get("/providers/keys", headers=_auth(user_b_token)).json()
    ids = {k["id"] for k in listing}
    assert shared_resp.json()["id"] in ids  # shared key visible to everyone
    assert own_resp.json()["id"] not in ids  # user A's personal key is not user B's


# --- authorization on status/rescan/delete ------------------------------------------------


def test_status_forbidden_for_unrelated_users_personal_key(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "huggingface", _no_op_adapter("huggingface"))
    _, owner_token = make_user("providers-owner@example.com")
    _, other_token = make_user("providers-other@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "huggingface", "api_key": "sk-x"},
        headers=_auth(owner_token),
    )
    key_id = create_resp.json()["id"]

    resp = client.get(f"/providers/keys/{key_id}/status", headers=_auth(other_token))
    assert resp.status_code == 403


def test_rescan_forbidden_for_unrelated_users_personal_key(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "huggingface", _no_op_adapter("huggingface"))
    _, owner_token = make_user("providers-owner2@example.com")
    _, other_token = make_user("providers-other2@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "huggingface", "api_key": "sk-x"},
        headers=_auth(owner_token),
    )
    key_id = create_resp.json()["id"]

    resp = client.post(f"/providers/keys/{key_id}/rescan", headers=_auth(other_token))
    assert resp.status_code == 403


def test_rescan_reruns_pipeline_and_can_recover_from_invalid_key(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeAdapter(name="openrouter", auth_type="api_key", validate_key_result=False)
    monkeypatch.setitem(ADAPTERS, "openrouter", fake)
    _, token = make_user("providers-rescan@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "openrouter", "api_key": "sk-was-bad"},
        headers=_auth(token),
    )
    key_id = create_resp.json()["id"]
    assert client.get(f"/providers/keys/{key_id}/status", headers=_auth(token)).json()[
        "outcome"
    ] == "invalid_key"

    # "fix" the key server-side and rescan
    fake.validate_key_result = True
    fake.discovered_models = [DiscoveredModel(model_id="m1", display_name="M1")]
    rescan_resp = client.post(f"/providers/keys/{key_id}/rescan", headers=_auth(token))
    assert rescan_resp.status_code == 200

    status_body = client.get(f"/providers/keys/{key_id}/status", headers=_auth(token)).json()
    assert status_body["outcome"] == "success"
    assert status_body["models_added"] == 1


def test_delete_provider_key_soft_revokes(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "huggingface", _no_op_adapter("huggingface"))
    _, token = make_user("providers-delete@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "huggingface", "api_key": "sk-x"},
        headers=_auth(token),
    )
    key_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/providers/keys/{key_id}", headers=_auth(token))
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "revoked"

    # still listed (soft delete), just revoked
    listing = client.get("/providers/keys", headers=_auth(token)).json()
    entry = next(k for k in listing if k["id"] == key_id)
    assert entry["status"] == "revoked"


def test_delete_forbidden_for_unrelated_users_personal_key(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "huggingface", _no_op_adapter("huggingface"))
    _, owner_token = make_user("providers-owner3@example.com")
    _, other_token = make_user("providers-other3@example.com")

    create_resp = client.post(
        "/providers/keys",
        json={"provider_name": "huggingface", "api_key": "sk-x"},
        headers=_auth(owner_token),
    )
    key_id = create_resp.json()["id"]

    resp = client.delete(f"/providers/keys/{key_id}", headers=_auth(other_token))
    assert resp.status_code == 403


def test_status_for_unknown_key_returns_404(client: TestClient, make_user: MakeUser) -> None:
    _, token = make_user("providers-unknownkey@example.com")
    resp = client.get("/providers/keys/999999/status", headers=_auth(token))
    assert resp.status_code == 404
