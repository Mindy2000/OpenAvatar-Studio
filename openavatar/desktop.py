from __future__ import annotations

import argparse
import json
import urllib.request
import os
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from openavatar import __version__

APP_NAME = "OpenAvatar Studio"


@dataclass(frozen=True)
class DesktopRuntime:
    host: str
    port: int
    url: str
    data_dir: Path


def find_free_port(preferred: int = 8767) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 80)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("找不到可用的本机端口")


def default_desktop_data_dir() -> Path:
    override = os.getenv("OPENAVATAR_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA", str(home / "AppData" / "Local")))
        return base / APP_NAME
    return Path(os.getenv("XDG_DATA_HOME", str(home / ".local" / "share"))) / "openavatar-studio"


def runtime_from_args(port: int) -> DesktopRuntime:
    selected_port = find_free_port(port)
    data_dir = default_desktop_data_dir()
    os.environ.setdefault("OPENAVATAR_DATA_DIR", str(data_dir))
    return DesktopRuntime("127.0.0.1", selected_port, f"http://127.0.0.1:{selected_port}", data_dir)


def start_server(runtime: DesktopRuntime) -> uvicorn.Server:
    # main creates the application on import, after the desktop data directory is set.
    from openavatar.main import app

    config = uvicorn.Config(app, host=runtime.host, port=runtime.port, log_level="info", access_log=False, use_colors=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="openavatar-server", daemon=True)
    thread.start()
    return server


def wait_until_ready(runtime: DesktopRuntime, timeout: float = 12.0, *, server=None) -> bool:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if server is not None and server.should_exit:
            return False
        try:
            if server is None or server.started:
                with opener.open(runtime.url + "/api/ready", timeout=0.5) as response:
                    health = json.loads(response.read(65536))
                if health.get("ok") is True and health.get("service") == "openavatar-studio" and "version" in health:
                    return True
        except (OSError, ValueError, AttributeError):
            pass
        time.sleep(0.2)
    return False


def desktop_language(data_dir: Path) -> str:
    """Read the saved interface preference without creating or modifying a database."""
    try:
        uri = (data_dir / "openavatar.sqlite").resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=0.1) as connection:
            row = connection.execute("SELECT value_json FROM app_settings WHERE key='interface_language'").fetchone()
        return "en-US" if row and json.loads(row[0]) == "en-US" else "zh-CN"
    except (OSError, sqlite3.Error, ValueError):
        return "zh-CN"


def show_startup_error() -> None:
    message = (
        "OpenAvatar failed to start. Check data-directory permissions and available ports, then retry."
        if desktop_language(default_desktop_data_dir()) == "en-US"
        else "OpenAvatar 启动失败。请检查数据目录是否可写、端口是否可用，然后重试。"
    )
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            messagebox.showerror(APP_NAME, message, parent=root)
        finally:
            root.destroy()
    except Exception:
        pass


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_tk_window(runtime: DesktopRuntime, server: uvicorn.Server) -> int:
    language = desktop_language(runtime.data_dir)

    def ui(zh: str, en: str) -> str:
        return en if language == "en-US" else zh

    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        print(ui(f"{APP_NAME} 已启动：{runtime.url}", f"{APP_NAME} started: {runtime.url}"))
        print(ui("关闭这个窗口或按 Ctrl+C 停止服务。", "Close this window or press Ctrl+C to stop the service."))
        try:
            while not server.should_exit:
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0

    root = tk.Tk()
    root.title(f"{APP_NAME} {__version__}")
    root.geometry("560x360")
    root.minsize(520, 320)
    root.configure(bg="#f7f4ee")

    localized_widgets: list[tuple[Any, str, str]] = []

    def label(text: str, size: int = 13, bold: bool = False) -> Any:
        font = ("Arial", size, "bold" if bold else "normal")
        return tk.Label(root, text=text, bg="#f7f4ee", fg="#23211f", font=font, wraplength=480, justify="left")

    label(f"{APP_NAME} {__version__}", 24, True).pack(anchor="w", padx=28, pady=(26, 6))
    def translated_label(zh: str, en: str, size: int = 13) -> Any:
        widget = label(ui(zh, en), size)
        localized_widgets.append((widget, zh, en))
        return widget

    translated_label("本地优先数字人工作室已经在这台电脑上运行。", "Your local-first avatar studio is running on this computer.").pack(anchor="w", padx=28)
    status = translated_label(f"访问地址：{runtime.url}\n数据目录：{runtime.data_dir}", f"Address: {runtime.url}\nData directory: {runtime.data_dir}", 11)
    status.pack(anchor="w", padx=28, pady=(18, 10))
    frame = tk.Frame(root, bg="#f7f4ee")
    frame.pack(anchor="w", padx=28, pady=8)
    for index, (zh, en, target) in enumerate([
        ("打开 OpenAvatar", "Open OpenAvatar", runtime.url),
        ("能力状态", "Capabilities", f"{runtime.url}/#capabilities"),
        ("诊断中心", "Diagnostics", f"{runtime.url}/#diagnostics"),
        ("数据目录", "Data Directory", str(runtime.data_dir)),
    ]):
        button = tk.Button(frame, text=ui(zh, en), command=lambda url=target: open_browser(url), width=18)
        button.grid(row=index // 2, column=index % 2, padx=(0, 10), pady=6)
        localized_widgets.append((button, zh, en))
    translated_label(
        "此内测版未签名，系统可能显示安全提示。API Key 保存在系统凭据库。",
        "This preview is unsigned and may trigger system security prompts. API keys stay in the system credential store.", 10,
    ).pack(anchor="w", padx=28, pady=(14, 0))

    def refresh_language() -> None:
        nonlocal language
        selected = desktop_language(runtime.data_dir)
        if selected != language:
            language = selected
            for widget, zh, en in localized_widgets:
                widget.configure(text=ui(zh, en))
        root.after(1000, refresh_language)

    root.after(1000, refresh_language)

    def close() -> None:
        if messagebox.askokcancel(ui("退出", "Quit"), ui("关闭 OpenAvatar Studio 本地服务？", "Stop the OpenAvatar Studio local service?")):
            server.should_exit = True
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAvatar Studio desktop launcher")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8767")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--credential-check", choices=("write", "read", "delete", "absent"), help=argparse.SUPPRESS)
    parser.add_argument("--credential-check-id", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.credential_check:
        from openavatar.credential_check import check_credential
        return check_credential(args.credential_check, args.credential_check_id)
    server = None
    try:
        runtime = runtime_from_args(args.port)
        runtime.data_dir.mkdir(parents=True, exist_ok=True)
        server = start_server(runtime)
        if not wait_until_ready(runtime, server=server):
            raise RuntimeError("Local service did not become ready")
    except Exception:
        if server is not None:
            server.should_exit = True
        show_startup_error()
        return 1
    try:
        if not args.no_browser:
            open_browser(runtime.url)
        return run_tk_window(runtime, server)
    finally:
        server.should_exit = True


if __name__ == "__main__":
    raise SystemExit(main())
