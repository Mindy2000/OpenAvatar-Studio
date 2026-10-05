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


def isolated_environment(folder: Path, base: str) -> dict[str, str]:
    # Do not inherit provider keys, proxy settings, or an existing data directory.
    runtime_names = {
        "PATH", "HOME", "USER", "LOGNAME", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
        "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "PLAYWRIGHT_BROWSERS_PATH",
    }
    env = {name: value for name, value in os.environ.items() if name in runtime_names}
    env.update({
        "OPENAVATAR_DATA_DIR": str(folder / "data"),
        "OPENAVATAR_TEST_URL": base,
        "OPENAVATAR_SCREENSHOT_DIR": str(folder / "artifacts"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "OLLAMA_URL": "http://127.0.0.1:1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


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
    with tempfile.TemporaryDirectory(prefix="openavatar-ui-") as temporary:
        folder = Path(temporary)
        env = isolated_environment(folder, base)
        output = folder / "artifacts"
        output.mkdir()
        log_path = folder / "ui-server.log"
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
                subprocess.run([sys.executable, "scripts/i18n_ui_checks.py", "--base-url", base], cwd=ROOT, env=env, check=True)
                subprocess.run([
                    sys.executable, "scripts/chat_ui_i18n_checks.py", "--base-url", base,
                    "--output", str(output / "chat-i18n"),
                ], cwd=ROOT, env=env, check=True)
                subprocess.run([sys.executable, "scripts/ui_smoke.py", "--base-url", base], cwd=ROOT, env=env, check=True)
                subprocess.run([sys.executable, "scripts/video_call_ui_checks.py", "--base-url", base], cwd=ROOT, env=env, check=True)
                subprocess.run([sys.executable, "scripts/timeline_ui_smoke.py"], cwd=ROOT, env=env, check=True)
            except Exception:
                log.flush()
                print("Local UI server log (last 40 lines):", file=sys.stderr)
                print("\n".join(log_path.read_text().splitlines()[-40:]), file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    print("Browser and WebSocket checks passed; temporary data and artifacts removed.")


if __name__ == "__main__":
    main()
