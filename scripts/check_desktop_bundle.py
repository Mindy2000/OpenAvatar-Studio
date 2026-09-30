"""Start the frozen application with disposable data and verify its core endpoints."""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import platform
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from openavatar import __version__


async def check_call(base: str, avatar_id: str) -> None:
    async with connect(f"{base.replace('http:', 'ws:')}/ws/avatars/{avatar_id}/call", origin=base) as ws:
        assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "call.started"
        await ws.send(json.dumps({"type": "ping"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "pong"
        await ws.send(json.dumps({"type": "call.end"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    dist = parser.parse_args().dist.resolve()
    system = platform.system()
    executable = dist / "OpenAvatar Studio" / ("OpenAvatar Studio.exe" if system == "Windows" else "OpenAvatar Studio")
    if system == "Darwin":
        executable = dist / "OpenAvatar Studio.app" / "Contents" / "MacOS" / "OpenAvatar Studio"
    assert executable.is_file(), executable
    # Separate frozen processes prove persistence across restarts, using no real key.
    import uuid
    account = str(uuid.uuid4())
    def credential_check(action):
        subprocess.run([str(executable), "--credential-check", action,
                        "--credential-check-id", account], check=True, timeout=30)
    try:
        credential_check("write")
        credential_check("read")
    finally:
        credential_check("delete")
    credential_check("absent")
    print(f"CREDENTIAL_STORE_OK {system} {platform.machine()}")
    # Inspect build inputs before the application has a chance to create runtime data.
    for path in dist.rglob("*"):
        assert path.suffix not in {".sqlite", ".db"}, f"Bundled database: {path}"
        assert path.name != ".env" and "demo_assets" not in path.parts, f"Private content: {path}"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    # Do not use host proxies even if the runner has them configured.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=10) as response:
            return response.read()

    with tempfile.TemporaryDirectory(prefix="openavatar-bundle-") as temporary:
        data = Path(temporary) / "data"
        env = {**os.environ, "OPENAVATAR_DATA_DIR": str(data)}
        for name in ("OPENAVATAR_API_KEY", "OPENAVATAR_ALIYUN_API_KEY", "OPENAVATAR_KIMI_API_KEY", "NORTH_API_KEY"):
            env.pop(name, None)
        log_path = ROOT / "output" / "desktop-smoke.log"
        log_path.parent.mkdir(exist_ok=True)
        with log_path.open("w") as log:
            process = subprocess.Popen([str(executable), "--no-browser", "--port", str(port)], cwd=temporary, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"Desktop exited with {process.returncode}; see {log_path}")
                    try:
                        assert json.loads(request("/api/health"))["version"] == __version__
                        break
                    except (OSError, urllib.error.URLError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"Desktop did not become ready; see {log_path}")
                        time.sleep(0.5)
                assert b"<html" in request("/").lower()
                english = json.loads(request("/api/i18n/en-US"))["messages"]
                assert english["literals"]["连接配置中心"] == "Connection Center"
                assert english["system"]["数字人不存在"] == "Avatar not found"
                assert json.loads(request("/api/i18n/zh-CN"))["messages"]["home.countUnit"] == "个项目"
                assert json.loads(request("/api/avatars")) == []
                assert json.loads(request("/api/templates/character"))["avatar_md"]
                avatar = json.loads(request("/api/avatars", {"name": "Bundle check", "subject_kind": "fictional", "consent_confirmed": True}))
                assert len(json.loads(request("/api/avatars"))) == 1
                asyncio.run(check_call(base, avatar["id"]))
                with zipfile.ZipFile(io.BytesIO(request(f"/api/avatars/{avatar['id']}/export", {}))) as archive:
                    assert json.loads(archive.read("manifest.json"))["version"] == 3
                assert (data / "openavatar.sqlite").is_file()
                assert process.poll() is None
                print(f"DESKTOP_BUNDLE_OK {system} {platform.machine()}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if process.returncode not in (0, -15, 1):
            print(f"Test process terminated with code {process.returncode}")


if __name__ == "__main__":
    main()
