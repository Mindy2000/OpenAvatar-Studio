"""Run browser and real WebSocket checks with disposable data and a local server."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from websockets.asyncio.client import connect


ROOT = Path(__file__).resolve().parents[1]


async def check_websocket(base: str) -> None:
    request = urllib.request.Request(
        f"{base}/api/avatars", method="POST",
        data=json.dumps({"name": "WebSocket test", "subject_kind": "fictional", "consent_confirmed": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        avatar_id = json.load(response)["id"]
    async with connect(f"{base.replace('http:', 'ws:')}/ws/avatars/{avatar_id}/call", origin=base) as ws:
        assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "call.started"
        await ws.send(json.dumps({"type": "ping"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "pong"
        await ws.send(json.dumps({"type": "call.end"}))


def main() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="openavatar-ui-") as folder:
        env = {**os.environ, "OPENAVATAR_DATA_DIR": folder, "OPENAVATAR_TEST_URL": base}
        log_path = ROOT / "output" / "ui-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "openavatar.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError(f"Server stopped; see {log_path}")
                    try:
                        with urllib.request.urlopen(f"{base}/api/health", timeout=1):
                            break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.2)
                else:
                    raise RuntimeError(f"Server not ready; see {log_path}")
                asyncio.run(check_websocket(base))
                subprocess.run([sys.executable, "scripts/ui_smoke.py", "--base-url", base], cwd=ROOT, env=env, check=True)
                subprocess.run([sys.executable, "scripts/timeline_ui_smoke.py"], cwd=ROOT, env=env, check=True)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    print("Browser and WebSocket checks passed; temporary data removed.")


if __name__ == "__main__":
    main()
