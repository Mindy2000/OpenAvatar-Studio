from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.desktop import default_desktop_data_dir, find_free_port, runtime_from_args
from openavatar.local_model import LocalModelError, validate_local_url
import openavatar.main as main_module
import openavatar.services.model_connections as model_connections
import openavatar.routes.archive as archive_routes
import openavatar.routes.avatars as avatar_routes
import openavatar.routes.imports as import_routes
import openavatar.routes.media_runtime as media_runtime_routes
import openavatar.routes.system as system_routes
import openavatar.services.video_generation as video_generation_module
import openavatar.services.provider_hub as provider_hub
from openavatar.main import create_app
from openavatar.providers import OpenAICompatibleClient
from scripts.build_desktop import build_command
from scripts.package_release import select_bundle
from openavatar.services.aliyun import AliyunAvatarClient
from openavatar.services.proactive import proactive_time_allowed
from openavatar.services.video_generation import VideoGenerationError, VideoGenerationSettings, download_video_result, poll_video_generation, start_openrouter_video


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "test.sqlite",
        avatars_dir=tmp_path / "avatars",
        exports_dir=tmp_path / "exports",
        ollama_url="http://127.0.0.1:9",
        ollama_model="test-local",
    )
    return TestClient(create_app(settings=settings))


def create_avatar(client: TestClient, **overrides):
    payload = {
        "name": "测试人物",
        "purpose": "本地测试",
        "relationship": "朋友",
        "subject_kind": "self",
        "adult_subject": True,
        "consent_confirmed": True,
    }
    payload.update(overrides)
    response = client.post("/api/avatars", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_is_local_only(tmp_path: Path):
    with make_client(tmp_path) as client:
        payload = client.get("/api/health").json()
        assert payload["ok"] is True
        assert payload["development_state"] == "local_workspace_only"
        assert payload["runtime_mode"] == "local"


def test_desktop_runtime_and_free_packaging_command(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path / "desktop-data"))
    assert default_desktop_data_dir() == (tmp_path / "desktop-data").resolve()
    runtime = runtime_from_args(find_free_port(9800))
    assert runtime.url.startswith("http://127.0.0.1:")
    assert runtime.data_dir == (tmp_path / "desktop-data").resolve()
    command = build_command()
    assert command[:3] == [sys.executable, "-m", "PyInstaller"]
    assert "openavatar/desktop.py" in command[-1].replace("\\", "/")
    assert any("openavatar/i18n" in item.replace("\\", "/") for item in command)
    dist = tmp_path / "dist"
    (dist / "OpenAvatar Studio.app").mkdir(parents=True)
    (dist / "OpenAvatar Studio").mkdir()
    assert select_bundle(dist, "macos").name == "OpenAvatar Studio.app"


def test_local_service_rejects_foreign_host_and_origin(tmp_path: Path):
    with make_client(tmp_path) as client:
        assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
        blocked = client.post("/api/avatars", headers={"Origin": "https://attacker.example"}, json={"name": "blocked"})
        assert blocked.status_code == 403


def test_database_upgrade_creates_one_local_backup(tmp_path: Path):
    path = tmp_path / "legacy.sqlite"
    import sqlite3

    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE app_settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at INTEGER NOT NULL)")
    Database(path).initialize()
    backup = tmp_path / "legacy.before-v4.backup.sqlite"
    assert backup.is_file()
    assert Database(path).one("SELECT value FROM schema_meta WHERE key='schema_version'")["value"] == "8"


def test_provider_hub_stores_key_outside_database_and_applies_capability_route(tmp_path: Path, monkeypatch):
    secrets = {}
    monkeypatch.setattr(provider_hub, "store_provider_key", lambda name, value: secrets.update({name: value}))
    monkeypatch.setattr(provider_hub, "load_provider_key", lambda name: secrets.get(name, ""))
    monkeypatch.setattr(provider_hub, "delete_provider_key", lambda name: secrets.pop(name, None))
    with make_client(tmp_path) as client:
        created = client.post("/api/provider-connections", json={
            "display_name": "MiniMax 直连",
            "provider_kind": "minimax",
            "base_url": "https://api.minimax.io/v1",
            "capabilities": ["chat", "tts", "voice_clone", "asr", "image", "video"],
            "models": {"chat": "MiniMax-M2.5", "tts": "speech-2.8-hd"},
            "consent": {"text": True, "audio": True, "voice_biometric": True, "image": True, "video": True},
            "budget": {"daily": 2, "monthly": 20},
            "api_key": "never-in-sqlite",
        })
        assert created.status_code == 201, created.text
        connection = created.json()
        assert connection["has_api_key"] is True
        route = client.put("/api/capability-routes", json={
            "scope_type": "global", "capability": "chat", "primary_connection_id": connection["id"],
            "fallback_connection_ids": [], "model": "MiniMax-M2.5", "config": {},
        })
        assert route.status_code == 200, route.text
        hub = client.get("/api/provider-hub").json()
        assert hub["routes"][0]["primary_connection_id"] == connection["id"]
        raw = (tmp_path / "test.sqlite").read_bytes()
        assert b"never-in-sqlite" not in raw


def test_database_preserves_malformed_file_before_failed_initialization(tmp_path: Path):
    import sqlite3

    path = tmp_path / "broken.sqlite"
    original = b"not-a-sqlite-database"
    path.write_bytes(original)
    try:
        Database(path).initialize()
    except sqlite3.DatabaseError:
        pass
    else:
        raise AssertionError("malformed database should not initialize")
    assert (tmp_path / "broken.before-v4.backup.sqlite").read_bytes() == original


def test_onboarding_and_diagnostics_are_local_user_flows(tmp_path: Path):
    with make_client(tmp_path) as client:
        onboarding = client.get("/api/onboarding")
        assert onboarding.status_code == 200
        assert onboarding.json()["completed"] is False
        saved = client.put("/api/onboarding", json={"completed": True})
        assert saved.status_code == 200
        assert saved.json()["style"] == "steps_with_inline_hints"
        diagnostics = client.get("/api/diagnostics")
        assert diagnostics.status_code == 200, diagnostics.text
        payload = diagnostics.json()
        assert payload["environment"]["data_dir"] == str(tmp_path)
        assert any(item["name"] == "本地数据库" for item in payload["checks"])
        assert "usage" in payload


def test_ocr_connections_and_capability_disclosure(tmp_path: Path):
    helper = tmp_path / "fake_ocr.py"
    helper.write_text(
        "import sys\nprint('测试截图文字')\n",
        encoding="utf-8",
    )
    with make_client(tmp_path) as client:
        saved = client.post("/api/ocr-connections", json={
            "display_name": "本地命令测试 OCR",
            "connection_type": "local_command",
            "provider_name": "fake",
            "command_template": f"{sys.executable} {helper} {{image}}",
        })
        assert saved.status_code == 201, saved.text
        connection_id = saved.json()["id"]
        selected = client.post(f"/api/ocr-connections/{connection_id}/select")
        assert selected.status_code == 200
        listed = client.get("/api/ocr-connections").json()
        assert listed["selected_ocr_connection_id"] == connection_id
        capabilities = client.get("/api/capabilities")
        assert capabilities.status_code == 200, capabilities.text
        ocr = next(item for item in capabilities.json()["items"] if item["key"] == "ocr")
        assert ocr["provider"] == "本地命令测试 OCR"
        deleted = client.delete(f"/api/ocr-connections/{connection_id}")
        assert deleted.status_code == 200


def test_fresh_system_has_no_demo_content(tmp_path: Path):
    with make_client(tmp_path) as client:
        assert client.get("/api/avatars").json() == []
        paths = client.get("/openapi.json").json()["paths"]
        assert not any(path.startswith("/api/examples") for path in paths)
        assert 'data-action="open-examples"' not in client.get("/").text


def test_authorized_person_requires_consent(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/avatars", json={
            "name": "某人", "subject_kind": "authorized_person", "consent_confirmed": False
        })
        assert response.status_code == 400


def test_cloud_model_url_is_rejected():
    try:
        validate_local_url("https://example.com")
    except LocalModelError:
        pass
    else:
        raise AssertionError("cloud URL should be rejected")


def test_cloud_mode_requires_explicit_data_consent(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.put("/api/settings/model", json={
            "mode": "cloud",
            "provider_name": "test",
            "base_url": "https://api.example.com",
            "model": "test-model",
            "cloud_data_consent": False,
        })
        assert response.status_code == 400


def test_openai_compatible_provider(tmp_path: Path):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.update(json.loads(self.rfile.read(length)))
            body = json.dumps({"choices": [{"message": {"content": "本地假服务响应"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleClient(f"http://127.0.0.1:{server.server_port}", "test-model", "test-key")
        reply = client.chat([{"role": "user", "content": "测试"}])
        assert reply == "本地假服务响应"
        assert received["model"] == "test-model"
    finally:
        server.shutdown()
        thread.join()


def test_migrated_aliyun_request_contracts(tmp_path: Path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), payload))
            if self.path.endswith("/audio/tts/customization"):
                result = {"output": {"voice": "voice-contract", "target_model": "target-contract"}}
            else:
                result = {"output": {"results": [{"url": "https://example.invalid/image.png"}]}}
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"RIFF-contract")
    image = tmp_path / "face.png"
    image.write_bytes(b"PNG-contract")
    try:
        provider = AliyunAvatarClient("key-contract", base_url=f"http://127.0.0.1:{server.server_port}")
        voice = provider.clone_voice(sample, preferred_name="openavatar1", clone_model="clone-contract", target_model="target-contract")
        visual = provider.generate_reference_image([image], prompt="自然照片", model="image-contract")
        assert voice["voice_id"] == "voice-contract"
        assert visual["output"]["results"]
        assert requests[0][1] == "Bearer key-contract"
        assert requests[0][2]["input"]["audio"]["data"].startswith("data:audio/x-wav;base64,")
        assert requests[1][2]["input"]["messages"][0]["content"][0]["image"].startswith("data:image/png;base64,")
        assert requests[1][2]["parameters"]["n"] == 1
    finally:
        server.shutdown()
        thread.join()


def test_api_key_is_not_returned_or_stored_in_database(tmp_path: Path, monkeypatch):
    secret = {"value": ""}
    monkeypatch.setattr(system_routes, "store_api_key", lambda value: secret.update(value=value))
    monkeypatch.setattr(system_routes, "load_api_key", lambda: secret["value"])
    with make_client(tmp_path) as client:
        response = client.put("/api/settings/model", json={
            "mode": "cloud",
            "provider_name": "test",
            "base_url": "https://api.example.com",
            "model": "test-model",
            "api_key": "super-secret-test-key",
            "cloud_data_consent": True,
        })
        assert response.status_code == 200, response.text
        settings = client.get("/api/settings/model").json()
        assert "api_key" not in settings
        assert settings["has_api_key"] is True
        assert b"super-secret-test-key" not in (tmp_path / "test.sqlite").read_bytes()


def test_import_analyze_edit_export_delete(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        data = json.dumps({"messages": [
            {"speaker": "测试人物", "content": "哈哈，今天还不错"},
            {"speaker": "用户", "content": "你晚上吃什么？"},
        ]}, ensure_ascii=False).encode()
        response = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=conversation",
            content=data,
            headers={"Content-Type": "application/json", "X-File-Name": "chat.json"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["memories"] == 0
        import_id = response.json()["id"]
        preview = client.get(f"/api/avatars/{avatar['id']}/imports/{import_id}/preview").json()
        assert preview["total"] == 2
        assert {item["speaker"] for item in preview["speakers"]} == {"测试人物", "用户"}
        confirmed = client.post(
            f"/api/avatars/{avatar['id']}/imports/{import_id}/confirm",
            json={"avatar_speakers": ["测试人物"], "excluded_row_ids": []},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["avatar_utterances"] == 1
        evidence = client.get(f"/api/avatars/{avatar['id']}/evidence").json()
        assert {row["derived_kind"] for row in evidence} >= {"conversation", "speaking_style"}

        profile = client.post(f"/api/avatars/{avatar['id']}/analyze").json()
        assert profile["source_count"] == 1
        assert profile["method"] == "local_heuristic"
        jobs = client.get(f"/api/avatars/{avatar['id']}/training-jobs").json()
        assert {job["job_type"] for job in jobs} >= {"memory", "persona"}
        assert all(job["status"] == "completed" for job in jobs)
        evaluation = client.post(f"/api/avatars/{avatar['id']}/evaluate")
        assert evaluation.status_code == 200
        assert 0 <= evaluation.json()["score"] <= 100
        assert {"required", "recommended", "advanced"} <= set(evaluation.json()["groups"])
        assert len(evaluation.json()["checks"]) >= 10

        updated = client.put(f"/api/avatars/{avatar['id']}/persona", json={
            "summary": "可编辑摘要", "traits": ["真实"], "speaking_style": "简短", "boundaries": "不编造"
        })
        assert updated.status_code == 200
        assert updated.json()["traits"] == ["真实"]

        exported = client.post(f"/api/avatars/{avatar['id']}/export")
        assert exported.status_code == 200
        assert exported.content.startswith(b"PK")
        package_path = tmp_path / "exported.openavatar.zip"
        package_path.write_bytes(exported.content)
        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["protocol"]["api_keys_are_never_exported"] is True
        assert manifest["privacy"]["contains_conversation_history"] is True
        inspected = client.post(
            "/api/packages/inspect",
            content=exported.content,
            headers={"Content-Type": "application/zip", "X-File-Name": "exported.openavatar.zip"},
        )
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["name"] == "测试人物"
        assert inspected.json()["contains_api_keys"] is False
        imported = client.post(
            "/api/packages/import",
            content=exported.content,
            headers={"Content-Type": "application/zip", "X-File-Name": "avatar.openavatar.zip", "X-Rights-Confirmed": "true"},
        )
        assert imported.status_code == 201, imported.text
        assert imported.json()["id"] != avatar["id"]
        assert client.get(f"/api/avatars/{imported.json()['id']}").status_code == 200

        wrong = client.delete(f"/api/avatars/{avatar['id']}?confirmation=错误")
        assert wrong.status_code == 400
        deleted = client.delete(f"/api/avatars/{avatar['id']}?confirmation=测试人物")
        assert deleted.status_code == 200


def test_package_exports_model_connection_hint_without_key(tmp_path: Path, monkeypatch):
    secrets = {}
    monkeypatch.setattr(model_connections, "store_provider_key", lambda provider, value: secrets.update({provider: value}))
    monkeypatch.setattr(model_connections, "load_provider_key", lambda provider: secrets.get(provider, ""))
    with make_client(tmp_path) as client:
        connection = client.post("/api/model-connections", json={
            "display_name": "导出提示 API",
            "connection_type": "cloud_openai",
            "provider_name": "hint-provider",
            "base_url": "https://api.example.com/v1",
            "model": "hint-model",
            "api_key": "package-secret",
            "cloud_data_consent": True,
        }).json()
        avatar = create_avatar(client)
        client.put(f"/api/avatars/{avatar['id']}/settings/model", json={"mode": "cloud", "connection_id": connection["id"]})
        exported = client.post(f"/api/avatars/{avatar['id']}/export")
        assert exported.status_code == 200
        package_path = tmp_path / "avatar.openavatar.zip"
        package_path.write_bytes(exported.content)
        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contains_api_keys"] is False
        assert manifest["model_connection_hint"]["provider_name"] == "hint-provider"
        assert "package-secret" not in exported.content.decode("utf-8", errors="ignore")
        imported = client.post(
            "/api/packages/import",
            content=exported.content,
            headers={"Content-Type": "application/zip", "X-File-Name": "avatar.openavatar.zip", "X-Rights-Confirmed": "true"},
        )
        assert imported.status_code == 201, imported.text
        imported_settings = client.get(f"/api/avatars/{imported.json()['id']}/settings/model").json()
        assert imported_settings["connection_id"] == ""


def test_package_privacy_filters_assets_and_remaps_visual_paths(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, name="可移植人物")
        image = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=image",
            content=b"\x89PNG\r\n\x1a\n",
            headers={"Content-Type": "image/png", "X-File-Name": "face.png"},
        )
        audio = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=audio",
            content=b"RIFF-test-audio",
            headers={"Content-Type": "audio/wav", "X-File-Name": "voice.wav"},
        )
        assert image.status_code == audio.status_code == 201
        generated_audio = tmp_path / "avatars" / avatar["id"] / "generated" / "audio" / "speech.mp3"
        generated_image = tmp_path / "avatars" / avatar["id"] / "generated" / "images" / "portrait.png"
        generated_video = tmp_path / "avatars" / avatar["id"] / "generated" / "video" / "turn.mp4"
        for path, content in ((generated_audio, b"audio"), (generated_image, b"image"), (generated_video, b"video")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        private = client.post(
            f"/api/avatars/{avatar['id']}/export?include_images=false&include_audio=false&include_conversations=false&include_call_history=false"
        )
        assert private.status_code == 200
        archive_path = tmp_path / "filtered.openavatar.zip"
        archive_path.write_bytes(private.content)
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            names = archive.namelist()
        assert manifest["privacy"]["contains_audio_files"] is False
        assert manifest["privacy"]["contains_image_files"] is False
        assert not any(name.endswith(("face.png", "voice.wav")) for name in names)
        assert not any(name.endswith(("speech.mp3", "portrait.png", "turn.mp4")) for name in names)

        full = client.post(f"/api/avatars/{avatar['id']}/export")
        imported = client.post(
            "/api/packages/import",
            content=full.content,
            headers={"Content-Type": "application/zip", "X-File-Name": "portable.openavatar.zip", "X-Rights-Confirmed": "true"},
        )
        assert imported.status_code == 201, imported.text
        new_id = imported.json()["id"]
        visual = client.get(f"/api/avatars/{new_id}/visual-assets").json()[0]
        assert visual["local_path"].startswith(f"avatars/{new_id}/")
        assert (tmp_path / visual["local_path"]).is_file()


def test_fictional_markdown_import_builds_persona_and_evidence(tmp_path: Path):
    with make_client(tmp_path) as client:
        templates = client.get("/api/templates/character")
        assert templates.status_code == 200
        assert "## 世界模型" in templates.json()["avatar_md"]
        assert "world_model:" in templates.json()["character_yaml"]

        avatar = create_avatar(
            client,
            name="星野澈",
            subject_kind="fictional",
            purpose="原创角色实验",
            consent_confirmed=True,
        )
        source = """# 星野澈原创角色设定

## 身份
- 星野澈是完全原创的虚构人物。
- 她住在一座海边城市，白天经营旧书店。

## 核心性格
- 安静但好奇
- 对陌生人保持边界
- 熟悉后会讲冷幽默

## 说话风格
- 中文短句，像即时聊天。
- 不使用客服腔。

## 世界模型
- 世界类型：现实城市。
- 主要地点：海边旧书店。
- 时间推进规则：程序运行时推进。

## 视觉身份
- 外貌方向：安静、清爽、书店气质。
- 批准规则：candidate -> approved -> canonical。

## 声音设定
- 声音来源：provider_builtin / local_tts / api_tts / none。
- 期望声线：自然中文女声。

## 不变规则
- 不对应任何现实人物。
- 不把未设定事实冒充过去经历。
"""
        response = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=fictional",
            content=source.encode(),
            headers={"Content-Type": "text/markdown", "X-File-Name": "avatar.md"},
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["status"] == "needs_review"
        assert payload["training_job"]["status"] == "waiting_review"
        second = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=fictional",
            content=source.encode(),
            headers={"Content-Type": "text/markdown", "X-File-Name": "second-avatar.md"},
        )
        assert second.status_code == 201
        before_confirm = client.get(f"/api/avatars/{avatar['id']}").json()
        assert before_confirm["persona"]["source_count"] == 0
        preview = client.get(f"/api/avatars/{avatar['id']}/imports/{payload['id']}/preview")
        assert preview.status_code == 200
        assert preview.json()["total"] >= 4
        confirmed = client.post(
            f"/api/avatars/{avatar['id']}/imports/{payload['id']}/confirm",
            json={"apply_mode": "merge"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["training_job"]["status"] == "completed"
        jobs = {job["id"]: job for job in client.get(f"/api/avatars/{avatar['id']}/training-jobs").json()}
        assert jobs[payload["training_job"]["id"]]["status"] == "completed"
        assert jobs[second.json()["training_job"]["id"]]["status"] == "waiting_review"
        repeated = client.post(f"/api/avatars/{avatar['id']}/imports/{payload['id']}/confirm", json={"apply_mode": "replace"})
        assert repeated.status_code == 409

        loaded = client.get(f"/api/avatars/{avatar['id']}").json()
        assert loaded["evidence_count"] >= 4
        assert loaded["persona"]["source_count"] >= 4
        assert "星野澈是完全原创" in loaded["persona"]["summary"]
        assert "安静但好奇" in loaded["persona"]["traits"]
        assert "即时聊天" in loaded["persona"]["speaking_style"]
        assert "不对应任何现实人物" in loaded["persona"]["boundaries"]
        checks = client.get(f"/api/avatars/{avatar['id']}/checks")
        assert checks.status_code == 200
        assert checks.json()["score"] >= 60
        built = client.post(f"/api/avatars/{avatar['id']}/build")
        assert built.status_code == 200, built.text
        second_build = client.post(f"/api/avatars/{avatar['id']}/build")
        assert second_build.status_code == 200, second_build.text
        world = client.get(f"/api/avatars/{avatar['id']}/world").json()
        assert {fact["fact_key"] for fact in world["facts"]} >= {
            "identity.display_name",
            "world.time_rule",
            "governance.virtual_world_not_real_news",
            "persona.summary",
        }
        proposals = client.get(f"/api/avatars/{avatar['id']}/world/proposals").json()
        assert any(item["status"] == "pending" for item in proposals)
        reviewed = client.post(
            f"/api/avatars/{avatar['id']}/world/proposals/{proposals[0]['id']}/review",
            json={"action": "approve", "note": "test"},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "approved"
        visual_asset = client.get(f"/api/avatars/{avatar['id']}/visual-assets").json()[0]
        assert visual_asset["status"] == "candidate"
        approved_visual = client.patch(
            f"/api/avatars/{avatar['id']}/visual-assets/{visual_asset['id']}",
            json={"status": "canonical", "note": "test approve"},
        )
        assert approved_visual.status_code == 200, approved_visual.text
        assert approved_visual.json()["status"] == "canonical"
        voices = client.get(f"/api/avatars/{avatar['id']}/voice-profiles").json()
        assert {voice["provider"] for voice in voices} >= {"piper", "browser", "none"}
        selected = client.post(f"/api/avatars/{avatar['id']}/voice-profiles/{voices[-1]['id']}/select")
        assert selected.status_code == 200, selected.text
        assert selected.json()["active"] is True
        assert client.get(f"/api/avatars/{avatar['id']}/rights").json()

        exported = client.post(f"/api/avatars/{avatar['id']}/export")
        imported = client.post(
            "/api/packages/import",
            content=exported.content,
            headers={"Content-Type": "application/zip", "X-File-Name": "fictional.openavatar.zip", "X-Rights-Confirmed": "true"},
        )
        assert imported.status_code == 201, imported.text
        imported_avatar = client.get(f"/api/avatars/{imported.json()['id']}").json()
        assert imported_avatar["evidence_count"] >= 4
        assert client.get(f"/api/avatars/{imported.json()['id']}/world").json()["facts"]
        assert client.get(f"/api/avatars/{imported.json()['id']}/visual-assets").json()
        assert client.get(f"/api/avatars/{imported.json()['id']}/voice-profiles").json()


def test_fictional_confirmation_returns_client_error_for_invalid_source(tmp_path: Path, monkeypatch):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, subject_kind="fictional")
        imported = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=fictional",
            content=b"# Valid at import time\n## Identity\n- Original character",
            headers={"Content-Type": "text/markdown", "X-File-Name": "avatar.md"},
        )
        assert imported.status_code == 201
        monkeypatch.setattr(import_routes, "parse_fictional_source", lambda *_args: (_ for _ in ()).throw(ValueError("bad template")))
        confirmed = client.post(f"/api/avatars/{avatar['id']}/imports/{imported.json()['id']}/confirm", json={"apply_mode": "merge"})
        assert confirmed.status_code == 400
        assert "bad template" in confirmed.json()["detail"]


def test_import_blocked_until_consent(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, subject_kind="fictional", consent_confirmed=False)
        response = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=conversation",
            content=b"A: hello",
            headers={"Content-Type": "text/plain", "X-File-Name": "chat.txt"},
        )
        assert response.status_code == 400


def test_audio_upload_creates_waiting_voice_job(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        response = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=audio",
            content=b"RIFF-test-audio",
            headers={"Content-Type": "audio/wav", "X-File-Name": "voice.wav"},
        )
        assert response.status_code == 201, response.text
        job = response.json()["training_job"]
        assert job["job_type"] == "voice"
        assert job["status"] == "waiting_configuration"
        evidence = client.get(f"/api/avatars/{avatar['id']}/evidence").json()
        assert evidence[0]["derived_kind"] == "voice_sample"
        assert "voice.wav" in evidence[0]["content"]
        transcripts = client.get(f"/api/avatars/{avatar['id']}/voice-transcriptions").json()
        assert transcripts[0]["status"] == "needs_review"
        confirmed = client.post(
            f"/api/avatars/{avatar['id']}/voice-transcriptions/{transcripts[0]['id']}/confirm",
            json={"transcript": "这是我说话的样本", "use_as_memory": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        evidence = client.get(f"/api/avatars/{avatar['id']}/evidence").json()
        assert "audio_transcript" in {row["derived_kind"] for row in evidence}


def test_image_ocr_confirmation_creates_real_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        import_routes,
        "extract_image_text",
        lambda _db, _path: {"text": "测试人物：这张截图里的话\n用户：我看到了", "note": "本地 OCR 已完成", "provider": "test-ocr", "data_location": "local"},
    )
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        response = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=image",
            content=b"fake-image",
            headers={"Content-Type": "image/png", "X-File-Name": "chat.png"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "needs_review"
        import_id = response.json()["id"]
        confirmed = client.post(
            f"/api/avatars/{avatar['id']}/imports/{import_id}/confirm",
            json={"avatar_speakers": [], "excluded_row_ids": []},
        )
        assert confirmed.status_code == 200, confirmed.text
        evidence = client.get(f"/api/avatars/{avatar['id']}/evidence").json()
        kinds = {row["derived_kind"] for row in evidence}
        assert {"image_asset", "image_ocr"} <= kinds


def test_cloud_voice_job_requires_confirmation_and_is_avatar_scoped(tmp_path: Path, monkeypatch):
    calls = []

    class FakeAliyun:
        def __init__(self, key):
            assert key == "test-aliyun-key"

        def available(self):
            return True

        def clone_voice(self, sample, **options):
            calls.append((sample, options))
            return {"voice_id": "voice-test-1", "target_model": options["target_model"], "raw_output": {}}

    monkeypatch.setattr(media_runtime_routes, "load_provider_key", lambda provider: "test-aliyun-key" if provider == "aliyun" else "")
    monkeypatch.setattr(media_runtime_routes, "AliyunAvatarClient", FakeAliyun)
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        client.app.state.db.set_setting("cloud_services", {
            "cloud_data_consent": True,
            "voice_clone_model": "clone-test",
            "voice_target_model": "target-test",
        })
        uploaded = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=audio",
            content=b"RIFF-test-audio",
            headers={"Content-Type": "audio/wav", "X-File-Name": "voice.wav"},
        ).json()
        job_id = uploaded["training_job"]["id"]
        denied = client.post(f"/api/avatars/{avatar['id']}/training-jobs/{job_id}/run", json={})
        assert denied.status_code == 400
        completed = client.post(
            f"/api/avatars/{avatar['id']}/training-jobs/{job_id}/run",
            json={"confirm_billable_call": True},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["result"]["voice_id"] == "voice-test-1"
        asset = client.app.state.db.one("SELECT * FROM provider_assets WHERE avatar_id=?", (avatar["id"],))
        assert asset and asset["external_id"] == "voice-test-1"
        assert len(calls) == 1


def test_cloud_visual_job_uses_latest_avatar_images(tmp_path: Path, monkeypatch):
    received = []

    class FakeAliyun:
        def __init__(self, _key):
            pass

        def available(self):
            return True

        def generate_reference_image(self, images, **options):
            received.extend(images)
            return {"output": {"results": [{"url": "https://example.invalid/generated.png"}]}}

    monkeypatch.setattr(media_runtime_routes, "load_provider_key", lambda _provider: "test-aliyun-key")
    monkeypatch.setattr(media_runtime_routes, "AliyunAvatarClient", FakeAliyun)
    def fake_download(_url, target, **_options):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG-generated")
        return "image/png"
    monkeypatch.setattr(media_runtime_routes, "download_provider_asset", fake_download)
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        client.app.state.db.set_setting("cloud_services", {"cloud_data_consent": True, "image_reference_model": "image-test"})
        latest_job = ""
        for index in range(4):
            response = client.post(
                f"/api/avatars/{avatar['id']}/imports?category=image",
                content=b"not-a-real-image",
                headers={"Content-Type": "image/png", "X-File-Name": f"face-{index}.png"},
            )
            assert response.status_code == 201
            latest_job = response.json()["training_job"]["id"]
        completed = client.post(
            f"/api/avatars/{avatar['id']}/training-jobs/{latest_job}/run",
            json={"confirm_billable_call": True},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["result"]["reference_count"] == 3
        asset_url = completed.json()["result"]["asset_url"]
        assert client.get(asset_url).content == b"PNG-generated"
        assert len(received) == 3
        visual_assets = client.get(f"/api/avatars/{avatar['id']}/visual-assets").json()
        assert len(visual_assets) >= 4


def test_model_routes_are_development_defaults_and_editable(tmp_path: Path):
    with make_client(tmp_path) as client:
        routes = client.get("/api/settings/model-routes")
        assert routes.status_code == 200, routes.text
        roles = {item["role"] for item in routes.json()}
        assert {"chat", "world_builder", "asr_batch", "tts"} <= roles
        updated = client.put(
            "/api/settings/model-routes/chat",
            json={
                "role": "ignored",
                "provider": "openrouter",
                "primary_model": "deepseek/deepseek-chat",
                "fallback_models": ["openrouter/auto"],
                "latency_class": "interactive",
                "cost_class": "cheap",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["primary_model"] == "deepseek/deepseek-chat"


def test_avatar_scoped_model_settings_do_not_use_global_key(tmp_path: Path, monkeypatch):
    secrets = {}

    def fake_store(provider, value):
        secrets[provider] = value

    def fake_load(provider):
        return secrets.get(provider, "")

    def fake_delete(provider):
        secrets.pop(provider, None)

    monkeypatch.setattr(avatar_routes, "store_provider_key", fake_store)
    monkeypatch.setattr(avatar_routes, "load_provider_key", fake_load)
    monkeypatch.setattr(avatar_routes, "delete_provider_key", fake_delete)
    monkeypatch.setattr(model_connections, "load_provider_key", fake_load)
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        denied = client.put(
            f"/api/avatars/{avatar['id']}/settings/model",
            json={
                "mode": "cloud",
                "provider_name": "any-openai-compatible",
                "base_url": "https://api.example.com/v1",
                "model": "cheap-model",
                "cloud_data_consent": True,
            },
        )
        assert denied.status_code == 400
        saved = client.put(
            f"/api/avatars/{avatar['id']}/settings/model",
            json={
                "mode": "cloud",
                "provider_name": "any-openai-compatible",
                "base_url": "https://api.example.com/v1",
                "model": "cheap-model",
                "api_key": "avatar-only-key",
                "cloud_data_consent": True,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["effective"]["inherited"] is False
        assert saved.json()["effective"]["model"] == "cheap-model"
        assert "avatar-only-key" not in (tmp_path / "test.sqlite").read_text(errors="ignore")


def test_model_connections_store_keys_outside_database_and_support_avatar_selection(tmp_path: Path, monkeypatch):
    secrets = {}

    def fake_store(provider, value):
        secrets[provider] = value

    def fake_load(provider):
        return secrets.get(provider, "")

    def fake_delete(provider):
        secrets.pop(provider, None)

    monkeypatch.setattr(model_connections, "store_provider_key", fake_store)
    monkeypatch.setattr(model_connections, "load_provider_key", fake_load)
    monkeypatch.setattr(model_connections, "delete_provider_key", fake_delete)
    class ReadyProvider:
        model = "cheap-chat"

        def available(self):
            return True

        def probe(self):
            return True

    monkeypatch.setattr(system_routes, "build_provider", lambda _config: ReadyProvider())
    with make_client(tmp_path) as client:
        created = client.post("/api/model-connections", json={
            "display_name": "我的任意 API",
            "connection_type": "cloud_openai",
            "provider_name": "any-compatible",
            "base_url": "https://api.example.com/v1",
            "model": "cheap-chat",
            "api_key": "connection-secret",
            "cloud_data_consent": True,
        })
        assert created.status_code == 201, created.text
        connection = created.json()
        assert connection["has_api_key"] is True
        assert "connection-secret" not in (tmp_path / "test.sqlite").read_text(errors="ignore")

        selected = client.post(f"/api/model-connections/{connection['id']}/select")
        assert selected.status_code == 200, selected.text
        listed = client.get("/api/model-connections").json()
        assert listed["selected_connection_id"] == connection["id"]

        avatar = create_avatar(client)
        saved = client.put(
            f"/api/avatars/{avatar['id']}/settings/model",
            json={"mode": "cloud", "connection_id": connection["id"]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["effective"]["model"] == "cheap-chat"
        before_test = client.get(f"/api/avatars/{avatar['id']}").json()["readiness"]
        assert not any(item["name"] == "模型设置" and item["passed"] for item in before_test["checks"])
        tested = client.post("/api/model-connections/test", json={
            "connection_id": connection["id"],
            "display_name": "我的任意 API",
            "connection_type": "cloud_openai",
            "provider_name": "any-compatible",
            "base_url": "https://api.example.com/v1",
            "model": "cheap-chat",
            "cloud_data_consent": True,
        })
        assert tested.status_code == 200 and tested.json()["ok"] is True
        readiness = client.get(f"/api/avatars/{avatar['id']}").json()["readiness"]
        assert any(item["name"] == "模型设置" and item["passed"] for item in readiness["checks"])

        deleted = client.delete(f"/api/model-connections/{connection['id']}")
        assert deleted.status_code == 200, deleted.text
        after = client.get(f"/api/avatars/{avatar['id']}/settings/model").json()
        assert after["mode"] == "inherit"
        assert after["connection_id"] == ""


def test_local_openai_and_custom_local_connection_validation(tmp_path: Path):
    with make_client(tmp_path) as client:
        local_openai = client.post("/api/model-connections", json={
            "display_name": "LM Studio",
            "connection_type": "local_openai",
            "provider_name": "LM Studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-chat",
        })
        assert local_openai.status_code == 201, local_openai.text
        custom = client.post("/api/model-connections", json={
            "display_name": "自定义本地适配器",
            "connection_type": "custom_local_adapter",
            "provider_name": "Local Adapter",
            "base_url": "http://localhost:8000/v1",
            "model": "adapter-chat",
            "adapter_kind": "openai_compatible",
        })
        assert custom.status_code == 201, custom.text
        rejected = client.post("/api/model-connections", json={
            "display_name": "错误本地地址",
            "connection_type": "local_openai",
            "provider_name": "bad",
            "base_url": "https://api.example.com/v1",
            "model": "bad-model",
        })
        assert rejected.status_code == 400


def test_model_connection_test_soft_fails_without_crashing(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/model-connections/test", json={
            "display_name": "错误连接",
            "connection_type": "cloud_openai",
            "provider_name": "bad",
            "base_url": "notaurl",
            "model": "bad-model",
            "api_key": "temporary",
            "cloud_data_consent": True,
        })
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is False


def test_chat_unavailable_message_matches_connection_type(tmp_path: Path):
    with make_client(tmp_path) as client:
        connection = client.post("/api/model-connections", json={
            "display_name": "LM Studio",
            "connection_type": "local_openai",
            "provider_name": "LM Studio",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "local-chat",
        }).json()
        avatar = create_avatar(client)
        saved = client.put(f"/api/avatars/{avatar['id']}/settings/model", json={"mode": "local", "connection_id": connection["id"]})
        assert saved.status_code == 200, saved.text
        response = client.post(f"/api/avatars/{avatar['id']}/chat", json={"message": "你好", "preview_mode": True})
        assert response.status_code == 502
        assert "Ollama" not in response.json()["detail"]
        assert "LM Studio" in response.json()["detail"]


def test_guided_builder_records_evidence_and_world_proposal(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, name="问答角色", subject_kind="fictional")
        state = client.get(f"/api/avatars/{avatar['id']}/guided-builder")
        assert state.status_code == 200, state.text
        assert state.json()["next_question"]["key"] == "identity"
        answered = client.post(
            f"/api/avatars/{avatar['id']}/guided-builder/answers",
            json={"question_key": "identity", "answer": "问答角色是完全原创的虚构人物，住在一座雨城。"},
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["progress"] >= 5
        assert any(module["key"] == "event_engine" for module in answered.json()["modules"])
        disabled = client.patch(
            f"/api/avatars/{avatar['id']}/guided-builder/modules/event_engine",
            json={"enabled": False},
        )
        assert disabled.status_code == 200, disabled.text
        assert any(module["key"] == "event_engine" and not module["enabled"] for module in disabled.json()["modules"])
        evidence = client.get(f"/api/avatars/{avatar['id']}/evidence").json()
        assert any(row["source_type"] == "guided_builder" for row in evidence)
        proposals = client.get(f"/api/avatars/{avatar['id']}/world/proposals").json()
        assert any(row["fact_key"] == "identity.guided_profile" for row in proposals)


def test_i18n_avatar_language_and_world_region_runtime(tmp_path: Path):
    with make_client(tmp_path) as client:
        english = client.get("/api/i18n/en-US").json()
        assert english["language"] == "en-US"
        assert english["selected"] == "zh-CN"
        assert english["messages"]["home.title"].startswith("Turn meaningful")
        saved_language = client.put("/api/settings/interface-language", json={"language": "en-US"})
        assert saved_language.status_code == 200, saved_language.text
        assert saved_language.json()["language"] == "en-US"

        options = client.get("/api/world-options").json()
        assert {item["key"] for item in options["world_regions"]} == {"mainland_china", "north_america", "japan", "europe", "custom"}
        avatar = create_avatar(
            client,
            name="Region Test",
            subject_kind="fictional",
            avatar_primary_language="en-US",
            avatar_response_mode="scene_based",
            world_region="japan",
            world_type="fictional",
        )
        loaded = client.get(f"/api/avatars/{avatar['id']}").json()
        assert loaded["language_profile"]["avatar_primary_language"] == "en-US"
        assert loaded["language_profile"]["world_region"] == "japan"

        guided = client.get(f"/api/avatars/{avatar['id']}/guided-builder").json()
        rules_question = next(item for item in guided["questions"] if item["key"] == "rules")
        assert "Japan" in rules_question["prompt"]
        assert rules_question["title"] == "What rules govern this world?"
        assert all(not any("\u4e00" <= char <= "\u9fff" for char in item["prompt"]) for item in guided["questions"])
        assert guided["language_profile"]["world_region"] == "japan"

        runtime = client.post(
            f"/api/avatars/{avatar['id']}/world/advance",
            json={"seconds": 3600, "force_minor_event": True},
        )
        assert runtime.status_code == 200, runtime.text
        assert runtime.json()["events"][-1]["payload"]["world_region"] == "japan"


def test_package_preserves_language_and_world_region_metadata(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(
            client,
            name="包协议角色",
            subject_kind="fictional",
            avatar_primary_language="en-US",
            avatar_response_mode="bilingual_mix",
            world_region="europe",
            world_type="hybrid",
        )
        exported = client.post(f"/api/avatars/{avatar['id']}/export")
        assert exported.status_code == 200, exported.text
        package_path = tmp_path / "exported-language-world.openavatar.zip"
        package_path.write_bytes(exported.content)
        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            language_profile = json.loads(archive.read("language_profile.json"))
            region_profile = json.loads(archive.read("world_region_profile.json"))
        assert manifest["language_profile"]["world_region"] == "europe"
        assert language_profile["avatar_primary_language"] == "en-US"
        assert region_profile["name_en"] == "Europe"

        inspected = client.post(
            "/api/packages/inspect",
            content=exported.content,
            headers={"Content-Type": "application/zip", "X-File-Name": "exported-language-world.openavatar.zip"},
        )
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["language_profile"]["world_region"] == "europe"

        imported = client.post(
            "/api/packages/import",
            content=exported.content,
            headers={
                "Content-Type": "application/zip",
                "X-File-Name": "exported-language-world.openavatar.zip",
                "X-Rights-Confirmed": "true",
            },
        )
        assert imported.status_code == 201, imported.text
        imported_avatar = client.get(f"/api/avatars/{imported.json()['id']}").json()
        assert imported_avatar["language_profile"]["avatar_primary_language"] == "en-US"
        assert imported_avatar["language_profile"]["world_region"] == "europe"


def test_empty_fictional_checks_normalize_legacy_severity_field(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, name="空设定角色", subject_kind="fictional")
        checks = client.get(f"/api/avatars/{avatar['id']}/checks")
        assert checks.status_code == 200, checks.text
        missing_source = next(item for item in checks.json()["checks"] if item["name"] == "虚构设定文件")
        assert missing_source["level"] == "required"


def test_quality_evaluation_records_feedback(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        evaluated = client.post(f"/api/avatars/{avatar['id']}/evaluate")
        assert evaluated.status_code == 200, evaluated.text
        rows = client.get(f"/api/avatars/{avatar['id']}/quality-evaluations").json()
        assert rows and rows[0]["evaluation_kind"] == "pre_use_readiness"
        assert rows[0]["samples"]
        feedback = client.post(
            f"/api/avatars/{avatar['id']}/quality-evaluations/{rows[0]['id']}/feedback",
            json={"rating": "off_style", "note": "语气不像"},
        )
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["user_feedback"]["items"][0]["rating"] == "off_style"


def test_real_route_rejects_audio_only_persona_build(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        uploaded = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=audio",
            content=b"RIFF-test-audio",
            headers={"Content-Type": "audio/wav", "X-File-Name": "voice.wav"},
        )
        assert uploaded.status_code == 201, uploaded.text
        checks = client.get(f"/api/avatars/{avatar['id']}/checks").json()
        text_check = next(item for item in checks["checks"] if item["name"] == "文本人格素材")
        assert text_check["passed"] is False
        analyzed = client.post(f"/api/avatars/{avatar['id']}/analyze")
        assert analyzed.status_code == 400
        assert "音频只能构建音色" in analyzed.text


def test_migrated_runtime_memory_persona_and_media_protocols(tmp_path: Path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, subject_kind="fictional")
        for key, answer in {
            "identity": "她是完全原创的虚构人物，住在一座会运行的城市。",
            "personality": "好奇、稳定、有边界。",
            "speaking_style": "短句，自然，不像客服。",
            "boundaries": "不对应真人，不编造未批准事实。",
        }.items():
            response = client.post(
                f"/api/avatars/{avatar['id']}/guided-builder/answers",
                json={"question_key": key, "answer": answer},
            )
            assert response.status_code == 200, response.text
        built = client.post(f"/api/avatars/{avatar['id']}/build")
        assert built.status_code == 200, built.text

        advanced = client.post(
            f"/api/avatars/{avatar['id']}/world/advance",
            json={"seconds": 3600, "force_minor_event": True},
        )
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["advanced"] is True
        rolled_back = client.post(f"/api/avatars/{avatar['id']}/world/rollback")
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["rolled_back"] is True
        consistency = client.post(f"/api/avatars/{avatar['id']}/world/consistency")
        assert consistency.status_code == 200

        graph = client.post(f"/api/avatars/{avatar['id']}/memory-graph/rebuild")
        assert graph.status_code == 200, graph.text
        core = client.post(f"/api/avatars/{avatar['id']}/persona-core/rebuild")
        assert core.status_code == 200, core.text
        assert core.json()["core"]["identity"]["route"] == "fictional"
        feedback = client.post(
            f"/api/avatars/{avatar['id']}/persona-feedback-rules",
            json={"dimension": "style", "signal": "off_style", "rule_text": "回复更短一点。", "weight": 0.8},
        )
        assert feedback.status_code == 201, feedback.text
        assert client.get(f"/api/avatars/{avatar['id']}/persona-feedback-rules").json()

        visual = client.get(f"/api/avatars/{avatar['id']}/visual-assets").json()[0]
        reviewed = client.post(f"/api/avatars/{avatar['id']}/visual-assets/{visual['id']}/review")
        assert reviewed.status_code == 200, reviewed.text
        media_rows = client.get(f"/api/avatars/{avatar['id']}/media-reviews").json()
        assert media_rows and media_rows[0]["findings"]

        call = client.post(f"/api/avatars/{avatar['id']}/calls", json={"provider": "protocol-only"})
        assert call.status_code == 201, call.text
        turn = client.post(
            f"/api/avatars/{avatar['id']}/calls/{call.json()['id']}/turns",
            json={"user_transcript": "你好", "assistant_text": "你好呀", "llm_latency_ms": 12},
        )
        assert turn.status_code == 201, turn.text
        ended = client.post(f"/api/avatars/{avatar['id']}/calls/{call.json()['id']}/end")
        assert ended.status_code == 200
        assert ended.json()["status"] == "ended"


def test_north_video_call_settings_and_session_protocol(tmp_path: Path, monkeypatch):
    secrets = {}

    def fake_store(provider, value):
        secrets[provider] = value

    def fake_load(provider):
        return secrets.get(provider, "")

    def fake_close(settings, north_session_id):
        assert settings["north_api_url"] == "https://north.example"
        assert north_session_id == "north-session-test"
        return {"ok": True, "released": north_session_id}

    def fake_start(settings, request, face_path=None):
        assert settings["north_api_url"] == "https://north.example"
        assert request.avatar_name == "视频角色"
        assert face_path and face_path.name.endswith("face.png")
        return {
            "ok": True,
            "provider": "north",
            "callId": request.call_id,
            "northSessionId": "north-session-test",
            "transport": "livekit",
            "streamMode": "realtime-passthrough",
            "layout": "avatar-primary",
            "avatar": {"kind": "north-realtime", "name": request.avatar_name},
            "livekit": {"url": "wss://livekit.example", "token": "lk-token", "room": "room-test"},
            "budget": {"pricePerSecond": 0.002, "billing": "elapsed-only"},
            "capabilities": {"livekit": True, "audioDriven": True, "sceneBackground": True, "cameraFlip": True},
            "metadata": {"protocol": "openavatar.video-call.north.v1", "north_session_id": "north-session-test", "price_per_second": 0.002},
        }

    monkeypatch.setattr(system_routes, "store_provider_key", fake_store)
    monkeypatch.setattr(system_routes, "load_provider_key", fake_load)
    monkeypatch.setattr(media_runtime_routes, "load_provider_key", fake_load)
    monkeypatch.setattr(media_runtime_routes, "start_north_video_call", fake_start)
    monkeypatch.setattr(media_runtime_routes, "close_north_session", fake_close)
    with make_client(tmp_path) as client:
        saved = client.put("/api/settings/cloud-services", json={
            "north_api_key": "north-secret",
            "north_api_url": "https://north.example",
            "north_idle_timeout": 120,
            "north_price_per_second": 0.002,
            "cloud_data_consent": True,
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["has_north_api_key"] is True
        assert "north-secret" not in (tmp_path / "test.sqlite").read_text(errors="ignore")
        avatar = create_avatar(client, name="视频角色", subject_kind="fictional")
        uploaded = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=image",
            content=b"\x89PNG\r\n\x1a\n",
            headers={"Content-Type": "image/png", "X-File-Name": "face.png"},
        )
        assert uploaded.status_code == 201, uploaded.text
        visual = client.get(f"/api/avatars/{avatar['id']}/visual-assets").json()[0]
        approved = client.patch(f"/api/avatars/{avatar['id']}/visual-assets/{visual['id']}", json={"status": "canonical"})
        assert approved.status_code == 200, approved.text
        status = client.get(f"/api/avatars/{avatar['id']}/video-call/status")
        assert status.status_code == 200, status.text
        assert status.json()["provider"] == "north"
        assert status.json()["hasCanonicalOrApprovedFace"] is True
        denied = client.post(f"/api/avatars/{avatar['id']}/calls", json={"mode": "video", "provider": "mock"})
        assert denied.status_code == 400
        call = client.post(
            f"/api/avatars/{avatar['id']}/calls",
            json={"mode": "video", "provider": "mock", "confirm_billable_call": True, "user_camera_enabled": True},
        )
        assert call.status_code == 201, call.text
        payload = call.json()
        assert payload["provider"] == "north"
        assert payload["video_call"]["transport"] == "livekit"
        assert payload["video_call"]["livekit"]["token"] == "lk-token"
        event = client.post(
            f"/api/avatars/{avatar['id']}/calls/{payload['id']}/events",
            json={"event_type": "video.avatar_state", "payload": {"state": "listening"}},
        )
        assert event.status_code == 201
        feedback = client.post(
            f"/api/avatars/{avatar['id']}/calls/{payload['id']}/vision-feedback",
            json={"feedback": "clear", "frame_summary": "口型正常"},
        )
        assert feedback.status_code == 201
        background = client.post(f"/api/avatars/{avatar['id']}/video-call/prepare-background", json={"mode": "scene", "prompt": "书桌"})
        assert background.status_code == 200
        assert background.json()["metadata"]["asset_role"] == "video_call_background"
        flip = client.post(f"/api/avatars/{avatar['id']}/video-call/flip-video", json={"mode": "flipped", "prompt": "看看桌面"})
        assert flip.status_code == 200, flip.text
        assert flip.json()["taskId"]
        ended = client.post(f"/api/avatars/{avatar['id']}/calls/{payload['id']}/end")
        assert ended.status_code == 200, ended.text
        metadata = json.loads(ended.json()["metadata_json"])
        assert metadata["north_close"]["released"] == "north-session-test"
        assert metadata["estimated_cost"] >= 0


def test_video_download_rejects_non_video_and_removes_partial_file(tmp_path: Path, monkeypatch):
    class Headers:
        @staticmethod
        def get_content_type():
            return "text/html"

    class Response:
        headers = Headers()

        @staticmethod
        def geturl():
            return "https://cdn.example/result.mp4"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Opener:
        @staticmethod
        def open(*_args, **_kwargs):
            return Response()

    monkeypatch.setattr(video_generation_module.urllib.request, "build_opener", lambda *_args: Opener())
    target = tmp_path / "partial.mp4"
    target.write_bytes(b"old-partial")
    try:
        download_video_result("https://cdn.example/result.mp4", target)
    except VideoGenerationError as exc:
        assert "不是视频" in str(exc)
    else:
        raise AssertionError("non-video response should fail")
    assert not target.exists()


def test_video_redirects_require_https_and_strip_cross_host_credentials():
    handler = video_generation_module._SafeVideoRedirectHandler()
    request = video_generation_module.urllib.request.Request(
        "https://openrouter.ai/api/v1/videos/task/content",
        headers={"Authorization": "Bearer secret"},
    )
    try:
        handler.redirect_request(request, None, 302, "Found", {}, "http://cdn.example/video.mp4")
    except VideoGenerationError:
        pass
    else:
        raise AssertionError("HTTP redirect should be rejected")
    redirected = handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.example/video.mp4")
    assert redirected.full_url == "https://cdn.example/video.mp4"
    assert redirected.get_header("Authorization") is None
    try:
        video_generation_module._NoAuthenticatedRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://attacker.example/capture"
        )
    except VideoGenerationError:
        pass
    else:
        raise AssertionError("authenticated API redirects should be rejected")


def test_aliyun_completed_video_requires_result_url(monkeypatch):
    class FakeAliyun:
        def __init__(self, _key):
            pass

        @staticmethod
        def poll_task(_task_id):
            return {"output": {"task_status": "SUCCEEDED"}}

    monkeypatch.setattr(video_generation_module, "AliyunAvatarClient", FakeAliyun)
    settings = VideoGenerationSettings(provider="aliyun", aliyun_api_key="test")
    try:
        poll_video_generation(settings, provider="aliyun", task_id="aliyun-task")
    except VideoGenerationError as exc:
        assert "没有返回有效视频地址" in str(exc)
    else:
        raise AssertionError("completed Aliyun task without output URL should fail")


def test_video_generation_job_submits_and_polls_async_provider(tmp_path: Path, monkeypatch):
    started = {}

    def fake_start(settings, *, prompt, first_frame, metadata=None):
        assert settings.provider in {"openrouter", "aliyun"}
        assert first_frame.startswith("data:image/png;base64,")
        assert "翻转镜头" in str(metadata.get("asset_role") or "") or metadata.get("asset_role") == "video_call_flip_video"
        started["prompt"] = prompt
        return {
            "ok": True,
            "provider": "openrouter",
            "task_id": "video-task-1",
            "status": "PENDING",
            "model": "google/veo-3.1-fast",
            "polling_url": "https://openrouter.example/poll/video-task-1",
            "metadata": {"tier": "fast"},
        }

    def fake_poll(settings, *, provider, task_id, polling_url=""):
        assert provider == "openrouter"
        assert task_id == "video-task-1"
        assert polling_url == "https://openrouter.example/poll/video-task-1"
        return {"ok": True, "done": True, "status": "SUCCEEDED", "remote_url": "https://cdn.example/video.mp4"}

    def fake_download(_url, target, *, api_key=""):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"video-bytes")
        return "video/mp4"

    monkeypatch.setattr(media_runtime_routes, "start_video_generation", fake_start)
    monkeypatch.setattr(media_runtime_routes, "poll_video_generation", fake_poll)
    monkeypatch.setattr(media_runtime_routes, "download_video_result", fake_download)
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, name="视频任务角色", subject_kind="fictional")
        client.app.state.db.set_setting("cloud_services", {"cloud_data_consent": True, "camera_flip_enabled": True, "scene_background_enabled": True})
        uploaded = client.post(
            f"/api/avatars/{avatar['id']}/imports?category=image",
            content=b"\x89PNG\r\n\x1a\n",
            headers={"Content-Type": "image/png", "X-File-Name": "face.png"},
        )
        assert uploaded.status_code == 201, uploaded.text
        visual = client.get(f"/api/avatars/{avatar['id']}/visual-assets").json()[0]
        client.patch(f"/api/avatars/{avatar['id']}/visual-assets/{visual['id']}", json={"status": "canonical"})
        flip = client.post(f"/api/avatars/{avatar['id']}/video-call/flip-video", json={"mode": "flipped", "prompt": "看看书桌"})
        assert flip.status_code == 200, flip.text
        job_id = flip.json()["taskId"]
        submitted = client.post(
            f"/api/avatars/{avatar['id']}/training-jobs/{job_id}/run",
            json={"confirm_billable_call": True},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "running"
        assert submitted.json()["result"]["provider_task_id"] == "video-task-1"
        completed = client.post(
            f"/api/avatars/{avatar['id']}/training-jobs/{job_id}/run",
            json={"confirm_billable_call": True},
        )
        assert completed.status_code == 200, completed.text
        payload = completed.json()
        assert payload["status"] == "needs_review"
        assert payload["result"]["asset_url"].endswith(".mp4")
        asset = client.get(payload["result"]["asset_url"])
        assert asset.status_code == 200
        assert asset.content == b"video-bytes"
        approved = client.post(
            f"/api/avatars/{avatar['id']}/continuity/runs/{payload['result']['continuity_run_id']}/approve"
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"


def test_cloned_speech_requires_confirmation_and_returns_audio(tmp_path: Path, monkeypatch):
    class FakeAliyun:
        def __init__(self, _key):
            pass

        def synthesize(self, text, **options):
            assert text == "你好"
            assert options["voice_id"] == "voice-test"
            return {"output": {"audio": {"url": "https://example.invalid/audio.mp3"}}}

    def fake_download(_url, target, **_options):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3-test")
        return "audio/mpeg"

    monkeypatch.setattr(archive_routes, "load_provider_key", lambda _provider: "test-aliyun-key")
    monkeypatch.setattr(archive_routes, "AliyunAvatarClient", FakeAliyun)
    monkeypatch.setattr(archive_routes, "download_provider_asset", fake_download)
    with make_client(tmp_path) as client:
        avatar = create_avatar(client)
        client.app.state.db.set_setting("cloud_services", {"cloud_data_consent": True, "voice_tts_model": "tts-test"})
        client.app.state.db.execute(
            "INSERT INTO provider_assets(avatar_id,kind,provider,external_id,created_at) VALUES(?,?,?,?,?)",
            (avatar["id"], "voice", "aliyun", "voice-test", 1),
        )
        denied = client.post(f"/api/avatars/{avatar['id']}/speech", json={"text": "你好"})
        assert denied.status_code == 400
        response = client.post(
            f"/api/avatars/{avatar['id']}/speech",
            json={"text": "你好", "confirm_billable_call": True},
        )
        assert response.status_code == 200, response.text
        assert response.content == b"ID3-test"
        assert response.headers["content-type"].startswith("audio/mpeg")


def test_aliyun_http_result_url_is_upgraded_to_https(tmp_path: Path, monkeypatch):
    from openavatar.services import aliyun as aliyun_module

    seen = {}

    class Response:
        headers = {"Content-Type": "audio/wav"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            if seen.get("read"):
                return b""
            seen["read"] = True
            return b"WAVE"

    def fake_open(request, **_options):
        seen["url"] = request.full_url
        return Response()

    monkeypatch.setattr(aliyun_module.urllib.request, "urlopen", fake_open)
    target = tmp_path / "voice.wav"
    media_type = aliyun_module.download_provider_asset(
        "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav?signature=x",
        target,
    )
    assert seen["url"].startswith("https://")
    assert target.read_bytes() == b"WAVE"
    assert media_type == "audio/wav"


def test_proactive_time_rules_support_quiet_hours_and_overnight_windows():
    noon = int(time.mktime((2026, 8, 12, 12, 0, 0, 0, 0, -1)))
    midnight = int(time.mktime((2026, 8, 12, 0, 30, 0, 0, 0, -1)))
    rules = {"allowed_windows": [{"start": "09:00", "end": "22:30"}], "quiet_hours": {"start": "23:00", "end": "08:30"}}
    assert proactive_time_allowed(rules, noon) is True
    assert proactive_time_allowed(rules, midnight) is False


def test_openrouter_video_uses_frame_images_and_rejects_untrusted_poll_url(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, payload=None, timeout=0):
        captured.update({"method": method, "url": url, "payload": payload})
        return {"id": "video-1", "status": "pending", "polling_url": "https://openrouter.ai/api/v1/videos/video-1"}

    from openavatar.services import video_generation as module

    monkeypatch.setattr(module, "_json_request", fake_request)
    settings = VideoGenerationSettings(provider="openrouter", openrouter_api_key="test", openrouter_model="google/veo-3.1-lite")
    started = start_openrouter_video(settings, prompt="test", first_frame="https://example.com/frame.png")
    assert started["task_id"] == "video-1"
    assert captured["payload"]["frame_images"][0]["frame_type"] == "first_frame"
    assert "references" not in captured["payload"]
    try:
        poll_video_generation(settings, provider="openrouter", task_id="video-1", polling_url="https://attacker.example/steal")
    except VideoGenerationError as exc:
        assert "不受信任" in str(exc)
    else:
        raise AssertionError("untrusted polling URL was accepted")
