from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

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


def wait_until_ready(runtime: DesktopRuntime, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            try:
                sock.connect((runtime.host, runtime.port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_tk_window(runtime: DesktopRuntime, server: uvicorn.Server) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        print(f"{APP_NAME} 已启动：{runtime.url}")
        print("关闭这个窗口或按 Ctrl+C 停止服务。")
        try:
            while not server.should_exit:
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("560x360")
    root.minsize(520, 320)
    root.configure(bg="#f7f4ee")

    def label(text: str, size: int = 13, bold: bool = False) -> Any:
        font = ("Arial", size, "bold" if bold else "normal")
        return tk.Label(root, text=text, bg="#f7f4ee", fg="#23211f", font=font, wraplength=480, justify="left")

    label(APP_NAME, 24, True).pack(anchor="w", padx=28, pady=(26, 6))
    label("本地优先数字人工作室已经在这台电脑上运行。", 13).pack(anchor="w", padx=28)
    status = label(f"访问地址：{runtime.url}\n数据目录：{runtime.data_dir}", 11)
    status.pack(anchor="w", padx=28, pady=(18, 10))

    frame = tk.Frame(root, bg="#f7f4ee")
    frame.pack(anchor="w", padx=28, pady=8)

    tk.Button(frame, text="打开 OpenAvatar", command=lambda: open_browser(runtime.url), width=18).grid(row=0, column=0, padx=(0, 10), pady=6)
    tk.Button(frame, text="能力状态", command=lambda: open_browser(f"{runtime.url}/#capabilities"), width=18).grid(row=0, column=1, padx=(0, 10), pady=6)
    tk.Button(frame, text="诊断中心", command=lambda: open_browser(f"{runtime.url}/#diagnostics"), width=18).grid(row=1, column=0, padx=(0, 10), pady=6)
    tk.Button(frame, text="数据目录", command=lambda: open_browser(str(runtime.data_dir)), width=18).grid(row=1, column=1, padx=(0, 10), pady=6)

    label("未签名内测版可能被系统提示风险；这是免费分发阶段的正常现象。API Key 仍保存到系统凭据库。", 10).pack(anchor="w", padx=28, pady=(14, 0))

    def close() -> None:
        if messagebox.askokcancel("退出", "关闭 OpenAvatar Studio 本地服务？"):
            server.should_exit = True
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAvatar Studio desktop launcher")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8767")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    runtime = runtime_from_args(args.port)
    runtime.data_dir.mkdir(parents=True, exist_ok=True)
    server = start_server(runtime)
    if wait_until_ready(runtime) and not args.no_browser:
        open_browser(runtime.url)
    return run_tk_window(runtime, server)


if __name__ == "__main__":
    raise SystemExit(main())
