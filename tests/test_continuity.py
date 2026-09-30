from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openavatar.config import Settings
from openavatar.main import create_app
from openavatar.services.minimax import MiniMaxClient, MiniMaxError
from openavatar.services.training import create_job, update_job
from openavatar.services.video_review import review_video_frames
from openavatar.services.video_runtime import video_call_face_path


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "continuity.sqlite",
        avatars_dir=tmp_path / "avatars",
        exports_dir=tmp_path / "exports",
        ollama_url="http://127.0.0.1:9",
        ollama_model="test-local",
    )
    return TestClient(create_app(settings=settings))


def create_avatar(client: TestClient) -> str:
    response = client.post(
        "/api/avatars",
        json={"name": "连续性人物", "subject_kind": "self", "adult_subject": True, "consent_confirmed": True},
    )
    assert response.status_code == 201
    return response.json()["id"]


def add_visual(client: TestClient, avatar_id: str, *, status: str = "canonical") -> int:
    now = int(time.time())
    return client.app.state.db.execute(
        "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,provider,metadata_json,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (avatar_id, "reference_image", status, "正面身份图", "test", "{}", now, now),
    )


def test_legacy_assets_become_identity_pack_and_video_contract(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar_id = create_avatar(client)
        asset_id = add_visual(client, avatar_id)
        organized = client.post(f"/api/avatars/{avatar_id}/visual-asset-sets/organize")
        assert organized.status_code == 200
        identity = organized.json()["sets"][0]
        assert identity["set_type"] == "identity"
        assert identity["status"] == "canonical"
        assert identity["items"][0]["visual_asset_id"] == asset_id

        plan = client.post(f"/api/avatars/{avatar_id}/continuity/plan", json={"prompt": "自然地挥手"})
        assert plan.status_code == 200
        contract = plan.json()["contract"]
        assert contract["ready_for_video"] is True
        assert contract["identity_set_id"] == identity["id"]
        assert contract["first_frame"]["visual_asset_id"] == asset_id


def test_scene_key_image_promotes_image_grounded_route(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar_id = create_avatar(client)
        add_visual(client, avatar_id)
        client.post(f"/api/avatars/{avatar_id}/visual-asset-sets/organize")
        scene = client.post(
            f"/api/avatars/{avatar_id}/scene-profiles",
            json={"display_name": "上海卧室", "semantic_key": "shanghai-bedroom", "stable_features": ["书桌位于窗户右侧"]},
        ).json()
        scene_set = client.post(
            f"/api/avatars/{avatar_id}/visual-asset-sets",
            json={"set_type": "scene", "semantic_key": "shanghai-bedroom", "label": "上海卧室", "status": "approved"},
        ).json()
        scene_asset_id = add_visual(client, avatar_id, status="approved")
        added = client.post(
            f"/api/avatars/{avatar_id}/visual-asset-sets/{scene_set['id']}/items",
            json={"visual_asset_id": scene_asset_id, "role": "first_frame", "status": "approved"},
        )
        assert added.status_code == 201
        plan = client.post(
            f"/api/avatars/{avatar_id}/continuity/plan",
            json={"prompt": "在上海卧室的书桌边看书", "hints": {"scene": "上海卧室"}},
        ).json()["contract"]
        assert plan["scene_profile_id"] == scene["id"]
        assert plan["scene_route"] == "image_grounded"
        assert plan["ready_for_video"] is True
        assert plan["first_frame"]["visual_asset_id"] == scene_asset_id


def test_video_gate_creates_linked_key_image_job(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar_id = create_avatar(client)
        add_visual(client, avatar_id)
        client.post(f"/api/avatars/{avatar_id}/visual-asset-sets/organize")
        scene = client.post(
            f"/api/avatars/{avatar_id}/scene-profiles",
            json={"display_name": "测试房间", "semantic_key": "test-room"},
        ).json()
        db = client.app.state.db
        db.set_setting("cloud_services", {"cloud_data_consent": True})
        job = create_job(db, avatar_id, "video", status="waiting_configuration")
        update_job(
            db,
            job["id"],
            result={"prompt": "在测试房间里自然走动", "continuity_hints": {"scene": "测试房间"}},
        )
        response = client.post(
            f"/api/avatars/{avatar_id}/training-jobs/{job['id']}/run",
            json={"confirm_billable_call": True},
        )
        assert response.status_code == 200
        blocked = response.json()
        assert blocked["status"] == "waiting_configuration"
        assert blocked["result"]["needs_key_image"] is True
        linked = db.one("SELECT * FROM training_jobs WHERE id=?", (blocked["result"]["key_image_job_id"],))
        assert linked and linked["job_type"] == "visual"
        assert scene["id"] in linked["result_json"]


def test_minimax_video_modes_are_capability_safe(monkeypatch):
    captured = {}
    client = MiniMaxClient("test-key")

    def fake_request(capability, payload, **_kwargs):
        captured.update({"capability": capability, "payload": payload})
        return {"task_id": "task-1"}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.create_video(
        "保持人物和物品一致",
        model="MiniMax-H3",
        reference_images=["https://example.com/a.png", "https://example.com/b.png"],
    )
    assert result["mode"] == "reference"
    assert result["reference_count"] == 2
    assert [item["role"] for item in captured["payload"]["content"][1:]] == ["reference_image", "reference_image"]

    with pytest.raises(MiniMaxError):
        client.create_video(
            "invalid mixed mode",
            model="MiniMax-H3",
            first_frame_url="https://example.com/frame.png",
            reference_images=["https://example.com/ref.png"],
        )


def test_video_call_never_uses_scene_key_image_as_face(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar_id = create_avatar(client)
        identity = tmp_path / "avatars" / avatar_id / "imports" / "image" / "face.png"
        scene = tmp_path / "avatars" / avatar_id / "generated" / "images" / "room.png"
        identity.parent.mkdir(parents=True, exist_ok=True)
        scene.parent.mkdir(parents=True, exist_ok=True)
        identity.write_bytes(b"face")
        scene.write_bytes(b"scene")
        now = int(time.time())
        db = client.app.state.db
        db.execute(
            "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,local_path,provider,metadata_json,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (avatar_id, "reference_image", "approved", "face", str(identity.relative_to(tmp_path)), "test", "{}", now, now),
        )
        db.execute(
            "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,local_path,provider,metadata_json,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (avatar_id, "scene_key_image", "canonical", "room", str(scene.relative_to(tmp_path)), "test", "{}", now, now),
        )
        assert video_call_face_path(db, client.app.state.settings, avatar_id) == identity


def test_missing_visual_reviewer_requires_manual_approval(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar_id = create_avatar(client)
        frame = tmp_path / "avatars" / avatar_id / "generated" / "video_keyframes" / "frame.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"frame")
        review = review_video_frames(
            client.app.state.db,
            client.app.state.settings,
            avatar_id=avatar_id,
            contract={"references": [], "invariants": [], "negative_constraints": []},
            keyframes=[{"local_path": str(frame.relative_to(tmp_path))}],
        )
        assert review["sendable"] is False
        assert review["manual_review"] is True
