"""API REST/WebSocket: autenticação, proteção de host, memórias, configurações e chat."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import TOKEN, text
from sexta.app import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(sexta):
    app = create_app(sexta=sexta)
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_public(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_api_requires_token(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer errado"}).status_code == 401
    response = client.get("/api/status", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["online"] is True and "cpu_percentual" in body["system"]


def test_untrusted_host_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 400


def test_security_headers_and_index(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


def test_memory_crud_export_import(client):
    created = client.post(
        "/api/memories", json={"content": "Gosto de café", "category": "preferencias"}, headers=AUTH
    ).json()
    memory_id = created["memory"]["id"]
    assert created["created"] is True
    assert client.get("/api/memories?q=cafe", headers=AUTH).json()[0]["id"] == memory_id
    patched = client.patch(f"/api/memories/{memory_id}", json={"pinned": True}, headers=AUTH).json()
    assert patched["pinned"] is True

    exported = client.get("/api/memories/export", headers=AUTH)
    assert "attachment" in exported.headers["content-disposition"]
    payload = exported.json()

    assert client.delete("/api/memories", headers=AUTH).status_code == 400  # exige confirmação
    assert client.delete("/api/memories", params={"confirm": "APAGAR TUDO"}, headers=AUTH).json()["deleted"] == 1
    assert client.post("/api/memories/import", json=payload, headers=AUTH).json()["created"] == 1
    stats = client.get("/api/memories/stats", headers=AUTH).json()
    assert stats["total"] == 1 and "preferencias" in stats["categories"]


def test_settings_roundtrip_and_validation(client):
    settings = client.get("/api/settings", headers=AUTH).json()
    assert settings["runtime"]["autonomy_level"] == 1
    assert "shell.exec" in settings["capabilities"]
    updated = client.put(
        "/api/settings", json={"autonomy_level": 2, "permission_overrides": {"shell.exec": "deny"}}, headers=AUTH
    )
    assert updated.status_code == 200
    assert updated.json()["permission_overrides"] == {"shell.exec": "deny"}
    assert client.put("/api/settings", json={"autonomy_level": 9}, headers=AUTH).status_code == 400


def test_chat_wait_and_conversation_endpoints(client, provider):
    provider.add([text("Olá, chefe!")])
    result = client.post("/api/chat", json={"text": "oi", "wait": True}, headers=AUTH).json()
    assert result["status"] == "done" and result["text"] == "Olá, chefe!"
    conv_id = result["conversation_id"]
    conversations = client.get("/api/conversations", headers=AUTH).json()
    assert conversations[0]["id"] == conv_id
    detail = client.get(f"/api/conversations/{conv_id}", headers=AUTH).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert "system_prompt" not in detail["conversation"]
    assert client.get("/api/search", params={"q": "chefe"}, headers=AUTH).json()[0]["conversation_id"] == conv_id
    assert client.get("/api/tasks", headers=AUTH).json()[0]["status"] == "done"
    assert client.delete(f"/api/conversations/{conv_id}", headers=AUTH).json()["status"] == "ok"
    assert client.get(f"/api/conversations/{conv_id}", headers=AUTH).status_code == 404


def test_chat_unknown_conversation(client):
    response = client.post("/api/chat", json={"text": "oi", "conversation_id": "naoexiste"}, headers=AUTH)
    assert response.status_code == 404


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=errado") as ws:
        ws.receive_json()


def test_websocket_chat_flow_with_approval(client, provider, settings):
    provider.add(
        [
            text("Criando."),
            {"type": "tool_use", "id": "tu1", "name": "fs_write", "input": {"path": "a.txt", "content": "oi"}},
        ],
        stop_reason="tool_use",
    ).add([text("Feito!")])
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "chat", "text": "crie a.txt", "client_ref": "r1"})
        seen = []
        while True:
            event = ws.receive_json()
            seen.append(event["type"])
            if event["type"] == "approval_required":
                ws.send_json({"type": "approval", "approval_id": event["approval_id"], "approved": True})
            if event["type"] == "task_done":
                assert event["status"] == "done"
                break
    assert "task_accepted" in seen and "approval_required" in seen and "tool_status" in seen
    assert (settings.workspace_dir / "a.txt").read_text() == "oi"


def test_panic_button_sets_restricted_mode(client):
    response = client.post("/api/tasks/cancel_all", json={"panic": True}, headers=AUTH).json()
    assert response["autonomy_level"] == 0
