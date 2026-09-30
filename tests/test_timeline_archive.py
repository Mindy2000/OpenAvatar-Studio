from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from openavatar.config import Settings
from openavatar.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "timeline.sqlite",
        avatars_dir=tmp_path / "avatars",
        exports_dir=tmp_path / "exports",
        ollama_url="http://127.0.0.1:9",
        ollama_model="test-local",
    )
    return TestClient(create_app(settings=settings))


def test_double_layer_timeline_edit_restore_and_isolation(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = client.post("/api/avatars", json={
            "name": "时间线人物", "purpose": "测试", "relationship": "恋人",
            "subject_kind": "self", "adult_subject": True, "consent_confirmed": True,
        }).json()
        avatar_id = avatar["id"]
        db = client.app.state.db
        now = int(time.time())
        history_id = db.execute(
            "INSERT INTO memories(avatar_id,speaker,content,kind,is_avatar,confidence,created_at,origin_kind) VALUES(?,?,?,?,?,?,?,?)",
            (avatar_id, "旧友", "永久真实聊天", "conversation", 1, 1.0, now - 1000, "imported_history"),
        )
        db.execute(
            "INSERT INTO world_facts(avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,confidence,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (avatar_id, "place", '"现实教室"', "real", "evolving", "fact", 1.0, 1, now, now),
        )
        official_ids = []
        for index, (role, content, media_url, media_type) in enumerate([
            ("user", "第一条正式聊天", "", ""),
            ("assistant", "第一次回复", "", ""),
            ("user", "需要改写", "/uploads/user.png", "image/png"),
            ("assistant", "之后的回复", "/generated/avatar.png", "image/png"),
        ]):
            official_ids.append(db.execute(
                "INSERT INTO messages(avatar_id,role,content,channel,created_at,media_url,media_type) VALUES(?,?,?,?,?,?,?)",
                (avatar_id, role, content, "chat", now + index, media_url, media_type),
            ))
        preview_ids = [
            db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,?,?,?,?)", (avatar_id, "user", "预览问题", "preview", now + 10)),
            db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,?,?,?,?)", (avatar_id, "assistant", "预览回答", "preview", now + 11)),
        ]
        db.execute(
            "INSERT INTO memories(avatar_id,speaker,content,kind,is_avatar,confidence,created_at,origin_kind,source_message_id,timeline_kind) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (avatar_id, "system", "由目标聊天产生的共同记忆", "runtime", 0, 0.8, now + 3, "runtime_chat", official_ids[2], "official"),
        )
        db.execute(
            "INSERT INTO world_events(avatar_id,event_key,title,summary,event_kind,status,occurred_at,payload_json,created_at,source_message_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (avatar_id, "chat_scene", "聊天推动的场景", "共同变化", "chat_caused", "fact", now + 3, "{}", now + 3, official_ids[2]),
        )

        history = client.get(f"/api/avatars/{avatar_id}/history?layer=historical").json()
        assert history["total"] == 1 and history["items"][0]["read_only"] is True
        corrected = client.put(
            f"/api/avatars/{avatar_id}/history/{history_id}/correction",
            json={"speaker": "旧友", "content": "校正后的显示", "note": "OCR校正"},
        )
        assert corrected.status_code == 200
        assert db.one("SELECT content FROM memories WHERE id=?", (history_id,))["content"] == "永久真实聊天"

        preview = client.post(f"/api/avatars/{avatar_id}/timeline/preview-change", json={
            "timeline_kind": "official", "action": "edit", "message_id": official_ids[2], "replacement_text": "改写后的聊天",
        })
        assert preview.status_code == 200, preview.text
        assert preview.json()["impact"]["affected_messages"] == 1
        changed = client.post(f"/api/avatars/{avatar_id}/timeline/apply-change", json={"preview_token": preview.json()["preview_token"]})
        assert changed.status_code == 200, changed.text
        frozen_branch = changed.json()["frozen_branch_id"]
        official = client.get(f"/api/avatars/{avatar_id}/history?layer=runtime&timeline_kind=official").json()
        assert [item["content"] for item in reversed(official["items"])] == ["第一条正式聊天", "第一次回复", "改写后的聊天"]
        preview_rows = client.get(f"/api/avatars/{avatar_id}/history?layer=runtime&timeline_kind=preview").json()
        assert {item["id"] for item in preview_rows["items"]} == set(preview_ids)
        assert db.one("SELECT fact_value_json FROM world_facts WHERE avatar_id=? AND fact_key='place'", (avatar_id,))["fact_value_json"] == '"现实教室"'
        assert db.one("SELECT COUNT(*) count FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat'", (avatar_id,))["count"] == 0
        assert db.one("SELECT COUNT(*) count FROM world_events WHERE avatar_id=? AND source_message_id=?", (avatar_id, official_ids[2]))["count"] == 0
        candidates = client.get(f"/api/avatars/{avatar_id}/timeline/media-candidates").json()
        assert any(item["reuse_policy"] == "automatic" for item in candidates)

        restored = client.post(f"/api/avatars/{avatar_id}/timeline/restore", json={"branch_id": frozen_branch})
        assert restored.status_code == 200, restored.text
        official = client.get(f"/api/avatars/{avatar_id}/history?layer=runtime&timeline_kind=official").json()
        assert len(official["items"]) == 4
        assert db.one("SELECT COUNT(*) count FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat'", (avatar_id,))["count"] == 1
        assert db.one("SELECT COUNT(*) count FROM world_events WHERE avatar_id=? AND source_message_id=?", (avatar_id, official_ids[2]))["count"] == 1

        delete_preview = client.post(f"/api/avatars/{avatar_id}/timeline/preview-change", json={
            "timeline_kind": "official", "action": "delete", "message_id": official_ids[0], "replacement_text": "",
        }).json()
        deleted = client.post(f"/api/avatars/{avatar_id}/timeline/apply-change", json={"preview_token": delete_preview["preview_token"]})
        assert deleted.status_code == 200 and deleted.json()["remaining_messages"] == 0
        assert client.get(f"/api/avatars/{avatar_id}/history?layer=historical").json()["total"] == 1
        assert client.get(f"/api/avatars/{avatar_id}/history?layer=runtime&timeline_kind=preview").json()["total"] == 2
        candidates = client.get(f"/api/avatars/{avatar_id}/timeline/media-candidates").json()
        user_candidate = next(item for item in candidates if item["origin_role"] == "user")
        refused = client.put(
            f"/api/avatars/{avatar_id}/timeline/media-candidates/{user_candidate['id']}",
            json={"status": "approved", "confirmed": False},
        )
        assert refused.status_code == 400
        approved = client.put(
            f"/api/avatars/{avatar_id}/timeline/media-candidates/{user_candidate['id']}",
            json={"status": "approved", "confirmed": True},
        )
        assert approved.status_code == 200
