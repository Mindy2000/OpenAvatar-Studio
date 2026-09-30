from __future__ import annotations

import os
import json
import zipfile
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openavatar.services.http_security import install_local_security, same_origin


def test_importing_desktop_does_not_initialize_database(tmp_path: Path):
    data = tmp_path / "unused-data"
    environment = {**os.environ, "OPENAVATAR_DATA_DIR": str(data)}
    subprocess.run([sys.executable, "-c", "import openavatar.desktop"], env=environment, check=True)
    assert not data.exists()


@pytest.mark.parametrize("origin", ["null", "", "malformed", "http://testserver:9000", "https://attacker.example", "http://[bad"])
def test_unsafe_browser_origins_cannot_write(origin: str):
    app = FastAPI()
    install_local_security(app)

    @app.post("/api/write")
    def write():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.post("/api/write", headers={"Origin": origin}).status_code == 403
        assert client.post("/api/write", headers={"Origin": "http://testserver"}).status_code == 200
        assert client.post("/api/write").status_code == 200


def test_websocket_origin_uses_matching_http_origin():
    assert same_origin("http://127.0.0.1:8767", "ws://127.0.0.1:8767/ws/avatar")
    assert not same_origin("http://127.0.0.1:9000", "ws://127.0.0.1:8767/ws/avatar")


def test_installed_server_has_websocket_protocol():
    from uvicorn.config import Config

    config = Config(FastAPI())
    config.load()
    assert config.ws_protocol_class is not None


@pytest.mark.parametrize("manifest", [[], {"format": "openavatar.package", "version": None}, {"format": "openavatar.package", "version": 3, "avatar": []}])
def test_invalid_package_manifest_is_a_validation_error(tmp_path: Path, manifest):
    from openavatar.services.packages import inspect_avatar_package

    path = tmp_path / "invalid.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("memories.json", "[]")
        archive.writestr("messages.json", "[]")
    with pytest.raises(ValueError):
        inspect_avatar_package(path)


@pytest.mark.parametrize("name", ["assets/../outside.txt", "assets\\..\\outside.txt", "C:/outside.txt"])
def test_package_paths_are_safe_on_all_platforms(name):
    from openavatar.services.packages import _validate_zip_members

    with pytest.raises(ValueError):
        _validate_zip_members([zipfile.ZipInfo(name)])
