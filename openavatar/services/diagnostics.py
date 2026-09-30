from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openavatar.config import ROOT, Settings
from openavatar.db import Database
from openavatar.local_model import LocalModelError, validate_local_url
from openavatar.services.ocr import detect_local_ocr


def _directory_writable(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".openavatar-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _check(name: str, status: str, detail: str, action: str = "") -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, "action": action}


def system_diagnostics(db: Database, settings: Settings, provider_status: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    data_ok = _directory_writable(settings.data_dir)
    avatars_ok = _directory_writable(settings.avatars_dir)
    exports_ok = _directory_writable(settings.exports_dir)
    checks.append(_check(
        "本地数据目录",
        "pass" if data_ok and avatars_ok and exports_ok else "fail",
        f"数据目录：{settings.data_dir}",
        "" if data_ok and avatars_ok and exports_ok else "请检查目录权限，或设置 OPENAVATAR_DATA_DIR 到可写目录。",
    ))
    try:
        db.one("SELECT COUNT(*) AS count FROM avatars")
        checks.append(_check("本地数据库", "pass", f"SQLite 数据库可用：{settings.database_path}"))
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        checks.append(_check("本地数据库", "fail", str(exc), "请关闭其他占用程序，或备份 data 后重启。"))
    connections = db.all("SELECT * FROM model_connections ORDER BY updated_at DESC")
    selected = str(db.setting("selected_model_connection_id", "") or "")
    if selected and any(row["id"] == selected for row in connections):
        checks.append(_check("默认模型连接", "pass", "已经选择默认模型连接。"))
    elif connections:
        checks.append(_check("默认模型连接", "warn", "已有模型连接，但尚未设为默认。", "在全局 AI 设置中选择一个默认连接。"))
    else:
        checks.append(_check("模型连接", "warn", "还没有模型连接。", "打开全局 AI 设置，添加云端 API 或本地模型连接。"))
    if provider_status.get("provider_available"):
        checks.append(_check("当前模型可用性", "pass", f"{provider_status.get('provider_name')} · {provider_status.get('model')}"))
    else:
        checks.append(_check(
            "当前模型可用性",
            "warn",
            f"{provider_status.get('provider_name')} · {provider_status.get('model')} 当前不可用。",
            "检查 API Key、模型名、本地服务是否启动，或换一个模型连接。",
        ))
    for row in connections:
        connection_type = str(row.get("connection_type", ""))
        base_url = str(row.get("base_url", ""))
        if connection_type in {"local_openai", "ollama", "custom_local_adapter"}:
            try:
                validate_local_url(base_url)
            except LocalModelError as exc:
                checks.append(_check(f"本地连接地址：{row.get('display_name')}", "fail", str(exc), "本地连接只能使用 127.0.0.1、localhost 或 ::1。"))
    detected_ocr = detect_local_ocr()
    has_automatic_ocr = any(item["id"] != "manual" for item in detected_ocr)
    custom_ocr = int((db.one("SELECT COUNT(*) AS count FROM ocr_connections WHERE enabled=1") or {"count": 0})["count"])
    checks.append(_check(
        "截图 OCR",
        "pass" if has_automatic_ocr or custom_ocr else "warn",
        f"已发现 {len([item for item in detected_ocr if item['id'] != 'manual'])} 个本机 OCR，已保存 {custom_ocr} 个自定义 OCR。",
        "" if has_automatic_ocr or custom_ocr else "截图仍会保存；可以手动补文字，或在全局设置里接入自己的 OCR。",
    ))
    launchers = [
        ROOT / "start.sh",
        ROOT / "start.command",
        ROOT / "start.bat",
        ROOT / "openavatar" / "desktop.py",
        ROOT / "scripts" / "build_desktop.py",
    ]
    existing_launchers = [path.name for path in launchers if path.exists()]
    checks.append(_check(
        "跨平台启动与桌面壳",
        "pass" if len(existing_launchers) >= 4 else "warn",
        f"已发现：{', '.join(existing_launchers) or '暂无启动器'}",
        "" if len(existing_launchers) >= 4 else "请确认桌面启动器和打包脚本随发布包一起分发。",
    ))
    avatar_count = int((db.one("SELECT COUNT(*) AS count FROM avatars") or {"count": 0})["count"])
    import_count = int((db.one("SELECT COUNT(*) AS count FROM imports") or {"count": 0})["count"])
    storage_bytes = sum(path.stat().st_size for path in settings.avatars_dir.rglob("*") if path.is_file()) if settings.avatars_dir.exists() else 0
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    return {
        "ok": fail_count == 0,
        "status": "fail" if fail_count else "warn" if warn_count else "pass",
        "summary": {"fail": fail_count, "warn": warn_count, "pass": sum(1 for item in checks if item["status"] == "pass")},
        "environment": {
            "data_dir": str(settings.data_dir),
            "database_path": str(settings.database_path),
            "avatars_dir": str(settings.avatars_dir),
            "exports_dir": str(settings.exports_dir),
            "openavatar_data_dir": os.getenv("OPENAVATAR_DATA_DIR", ""),
        },
        "usage": {"avatars": avatar_count, "imports": import_count, "asset_storage_bytes": storage_bytes},
        "checks": checks,
    }
