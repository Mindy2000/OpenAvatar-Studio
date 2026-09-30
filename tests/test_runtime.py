from __future__ import annotations

import json
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import openavatar.main as main_module
from openavatar.config import Settings
from openavatar.db import Database
from openavatar.events import EventStore
from openavatar.main import create_app
from openavatar.runtime import LeaseManager, Metrics, RunRegistry


class FakeStreamingProvider:
    model = "fake-stream"

    def available(self) -> bool:
        return True

    def chat(self, messages, *, json_mode=False) -> str:
        return "你好，流式世界"

    def stream_chat(self, messages):
        yield "你好，"
        yield "流式世界"


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "runtime.sqlite",
        avatars_dir=tmp_path / "avatars",
        exports_dir=tmp_path / "exports",
        ollama_url="http://127.0.0.1:9",
        ollama_model="test-local",
    )
    monkeypatch.setattr(main_module, "model_client", lambda *_args: FakeStreamingProvider())
    monkeypatch.setattr(main_module, "completion_report", lambda *_args: {"can_start_official": True})
    return TestClient(create_app(settings=settings))


def create_avatar(client: TestClient) -> str:
    response = client.post(
        "/api/avatars",
        json={"name": "流式人物", "subject_kind": "self", "adult_subject": True, "consent_confirmed": True},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_stream_chat_persists_turn_and_reports_metrics(tmp_path: Path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar_id = create_avatar(client)
        response = client.post(f"/api/avatars/{avatar_id}/chat/stream", json={"message": "测试流式回复"})
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [event["type"] for event in events] == ["start", "delta", "delta", "done"]
        assert events[-1]["reply"] == "你好，流式世界"
        messages = client.get(f"/api/avatars/{avatar_id}/messages").json()
        assert [item["content"] for item in messages[-2:]] == ["测试流式回复", "你好，流式世界"]
        runtime = client.get("/api/runtime/metrics").json()
        assert runtime["database"]["ok"] is True
        assert runtime["metrics"]["observations"]["chat.first_text_ms"]["count"] == 1


def test_text_realtime_gateway_records_call_turn(tmp_path: Path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar_id = create_avatar(client)
        with client.websocket_connect(f"/ws/avatars/{avatar_id}/call") as socket:
            started = socket.receive_json()
            assert started["type"] == "call.started"
            socket.send_json([])
            assert socket.receive_json()["type"] == "call.error"
            socket.send_json({"type": "ping"})
            assert socket.receive_json()["type"] == "pong"
            socket.send_json({"type": "user.text", "text": "你好"})
            assert socket.receive_json()["type"] == "user.committed"
            received = []
            while True:
                event = socket.receive_json()
                received.append(event)
                if event["type"] == "assistant.done":
                    break
            assert "".join(item["text"] for item in received if item["type"] == "assistant.delta") == "你好，流式世界"
            socket.send_json({"type": "call.end"})
        row = client.app.state.db.one(
            "SELECT * FROM realtime_call_turns WHERE avatar_id=? ORDER BY id DESC LIMIT 1", (avatar_id,)
        )
        assert row and row["assistant_text"] == "你好，流式世界"


def test_private_export_omits_chat_copies_in_diagnostics(tmp_path: Path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar_id = create_avatar(client)
        marker = "PRIVATE_CHAT_SENTINEL_4f87"
        assert client.post(f"/api/avatars/{avatar_id}/chat/stream", json={"message": marker}).status_code == 200
        full = client.post(f"/api/avatars/{avatar_id}/export")
        private = client.post(f"/api/avatars/{avatar_id}/export?include_conversations=false&include_call_history=false")
        assert full.status_code == private.status_code == 200
        assert full.headers["content-disposition"] != private.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(full.content)) as archive:
            assert marker.encode() in archive.read("decision_explanations.json")
        with zipfile.ZipFile(io.BytesIO(private.content)) as archive:
            assert all(marker.encode() not in archive.read(name) for name in archive.namelist())


def test_event_store_leases_backup_and_cancellation(tmp_path: Path):
    db = Database(tmp_path / "runtime.sqlite")
    db.initialize()
    first = LeaseManager(db, "first")
    second = LeaseManager(db, "second")
    assert first.acquire("worker", 30) is True
    assert second.acquire("worker", 30) is False
    first.release_all()
    assert second.acquire("worker", 30) is True

    store = EventStore(db)
    event_id = store.append("avatar-1", "test.created", {"safe": True}, idempotency_key="same", publish=True)
    assert store.append("avatar-1", "test.created", {}, idempotency_key="same", publish=True) == event_id
    claimed = store.claim()
    assert len(claimed) == 1
    store.delivered(claimed[0]["outbox_id"])

    registry = RunRegistry()
    run_id, cancelled = registry.start("avatar-1", "chat")
    assert registry.cancel(run_id, "avatar-1") is True and cancelled.is_set()
    registry.finish(run_id)
    assert registry.snapshot() == []

    metrics = Metrics()
    metrics.increment("ok")
    metrics.observe("latency", 12.5)
    assert metrics.snapshot()["counters"]["ok"] == 1
    backup = db.backup(tmp_path / "backups" / "copy.sqlite")
    assert backup.is_file() and Database(backup).integrity_check()["ok"] is True


def test_backup_api_requires_confirmation_and_restores_consistent_database(tmp_path: Path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar_id = create_avatar(client)
        created = client.post("/api/system/backup")
        assert created.status_code == 200
        filename = created.json()["filename"]
        client.app.state.db.execute("DELETE FROM avatars WHERE id=?", (avatar_id,))
        refused = client.post(f"/api/system/backups/{filename}/restore", params={"confirmation": "wrong"})
        assert refused.status_code == 400
        restored = client.post(
            f"/api/system/backups/{filename}/restore",
            params={"confirmation": "RESTORE OPENAVATAR DATABASE"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["integrity"]["ok"] is True
        assert client.app.state.db.one("SELECT id FROM avatars WHERE id=?", (avatar_id,)) is not None


def test_world_clock_runs_for_a_year_without_event_storms(tmp_path: Path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar_id = create_avatar(client)
        for _ in range(52):
            response = client.post(
                f"/api/avatars/{avatar_id}/world/advance",
                json={"seconds": 7 * 86400, "force_minor_event": False},
            )
            assert response.status_code == 200, response.text
        response = client.post(
            f"/api/avatars/{avatar_id}/world/advance",
            json={"seconds": 86400, "force_minor_event": False},
        )
        assert response.status_code == 200
        state = response.json()
        facts = {item["fact_key"]: item["value"] for item in state["facts"]}
        assert facts["runtime.day_index"] == 365
        assert facts["runtime.current_activity"]
        event_count = client.app.state.db.one(
            "SELECT COUNT(*) count FROM world_events WHERE avatar_id=?", (avatar_id,)
        )["count"]
        assert event_count <= 53
