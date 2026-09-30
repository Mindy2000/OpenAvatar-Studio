from __future__ import annotations

import base64
import json
import platform
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openavatar.db import Database
from openavatar.local_model import LocalModelError, validate_local_url
from openavatar.providers import ProviderError, delete_provider_key, load_provider_key, scoped_provider_key_name, store_provider_key, verified_ssl_context


OCR_TYPES = {"local_command", "local_http", "cloud_api"}
DANGEROUS_LOCAL_COMMANDS = {
    "bash", "sh", "zsh", "fish", "cmd", "powershell", "pwsh", "sudo", "su",
    "rm", "mv", "cp", "chmod", "chown", "curl", "wget", "scp", "ssh", "osascript",
}


def provider_key(connection_id: str) -> str:
    return scoped_provider_key_name("ocr_connection", connection_id)


def detect_local_ocr() -> list[dict[str, Any]]:
    system = platform.system()
    engines: list[dict[str, Any]] = []
    if system == "Darwin":
        engines.append({
            "id": "system_macos_vision",
            "display_name": "macOS 系统 OCR",
            "connection_type": "system",
            "status": "available",
            "local_only": True,
            "data_location": "local",
            "note": "可由未来桌面壳直接调用 Apple Vision；当前浏览器本地版会优先使用已安装命令行 OCR。",
        })
    if system == "Windows":
        engines.append({
            "id": "system_windows_ocr",
            "display_name": "Windows 系统 OCR",
            "connection_type": "system",
            "status": "available",
            "local_only": True,
            "data_location": "local",
            "note": "可由未来桌面壳直接调用 Windows OCR；当前浏览器本地版会优先使用已安装命令行 OCR。",
        })
    tesseract = shutil.which("tesseract")
    if tesseract:
        engines.append({
            "id": "builtin_tesseract",
            "display_name": "Tesseract",
            "connection_type": "local_command",
            "status": "available",
            "local_only": True,
            "data_location": "local",
            "command": tesseract,
            "note": "已发现本机 Tesseract，可离线识别截图文字。",
        })
    for command, label in (("paddleocr", "PaddleOCR"), ("easyocr", "EasyOCR")):
        path = shutil.which(command)
        if path:
            engines.append({
                "id": f"detected_{command}",
                "display_name": label,
                "connection_type": "local_command",
                "status": "detected",
                "local_only": True,
                "data_location": "local",
                "command": path,
                "note": "已发现命令，但不同安装方式输出格式不一致，建议在自定义 OCR 中保存命令模板。",
            })
    if not engines:
        engines.append({
            "id": "manual",
            "display_name": "手动补文字",
            "connection_type": "manual",
            "status": "available",
            "local_only": True,
            "data_location": "local",
            "note": "未发现可直接调用的本机 OCR。截图会保存，用户仍可手动补充文字。",
        })
    return engines


def public_ocr_connection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "connection_type": row["connection_type"],
        "provider_name": row["provider_name"],
        "command_template": row["command_template"],
        "base_url": row["base_url"],
        "api_key_required": bool(row.get("api_key_required", False)),
        "cloud_data_consent": bool(row.get("cloud_data_consent", False)),
        "local_only": bool(row.get("local_only", True)),
        "enabled": bool(row.get("enabled", True)),
        "has_api_key": bool(load_provider_key(provider_key(str(row["id"])))),
        "last_test_status": row.get("last_test_status", "untested"),
        "last_test_message": row.get("last_test_message", ""),
        "updated_at": row.get("updated_at", 0),
    }


def validate_ocr_payload(payload: dict[str, Any], connection_id: str = "") -> dict[str, Any]:
    connection_type = str(payload.get("connection_type", "local_command"))
    if connection_type not in OCR_TYPES:
        raise ProviderError("不支持的 OCR 类型")
    row = {
        "id": connection_id or "preview",
        "display_name": str(payload.get("display_name", "我的 OCR") or "我的 OCR").strip()[:80],
        "connection_type": connection_type,
        "provider_name": str(payload.get("provider_name", "") or payload.get("display_name", "自定义 OCR")).strip()[:80],
        "command_template": str(payload.get("command_template", "") or "").strip()[:1000],
        "base_url": str(payload.get("base_url", "") or "").strip().rstrip("/")[:500],
        "api_key_required": int(bool(payload.get("api_key_required", False))),
        "cloud_data_consent": int(bool(payload.get("cloud_data_consent", False))),
        "local_only": int(connection_type != "cloud_api"),
        "enabled": int(bool(payload.get("enabled", True))),
    }
    if connection_type == "local_command":
        try:
            parts = shlex.split(row["command_template"])
        except ValueError as exc:
            raise ProviderError("本地命令模板格式不正确") from exc
        if not parts or "{image}" not in parts:
            raise ProviderError("本地命令模板必须包含独立的 {image} 参数")
        if any("{image}" in part and part != "{image}" for part in parts):
            raise ProviderError("{image} 必须作为独立参数，避免路径空格或特殊字符导致识别失败")
        executable = parts[0]
        if Path(executable).name.lower() in DANGEROUS_LOCAL_COMMANDS:
            raise ProviderError("为了安全，OCR 命令不能直接调用 shell、下载器、远程连接或文件管理命令")
        if not shutil.which(executable) and not Path(executable).exists():
            raise ProviderError("找不到本地 OCR 命令")
    elif connection_type == "local_http":
        if not row["base_url"]:
            raise ProviderError("请填写本地 OCR 服务地址")
        validate_local_url(row["base_url"])
    elif connection_type == "cloud_api":
        parsed = urlparse(row["base_url"])
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProviderError("云端 OCR API 必须使用 HTTPS")
        if not row["cloud_data_consent"]:
            raise ProviderError("使用云端 OCR 前必须确认图片会发送给该服务商")
    return row


def upsert_ocr_connection(db: Database, payload: dict[str, Any], connection_id: str = "") -> dict[str, Any]:
    existing = db.one("SELECT * FROM ocr_connections WHERE id=?", (connection_id,)) if connection_id else None
    row = validate_ocr_payload(payload, connection_id or (existing or {}).get("id", ""))
    row["id"] = str((existing or {}).get("id") or f"ocr_{time.time_ns():x}") if not connection_id else connection_id
    key_name = provider_key(row["id"])
    if payload.get("clear_api_key"):
        delete_provider_key(key_name)
    api_key = str(payload.get("api_key", "") or "").strip()
    if api_key:
        store_provider_key(key_name, api_key)
    if row["connection_type"] == "cloud_api" and row["api_key_required"] and not load_provider_key(key_name):
        raise ProviderError("云端 OCR 需要填写 API Key")
    now = int(time.time())
    db.execute(
        """
        INSERT INTO ocr_connections
        (id,display_name,connection_type,provider_name,command_template,base_url,api_key_required,cloud_data_consent,local_only,enabled,last_test_status,last_test_message,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          display_name=excluded.display_name,
          connection_type=excluded.connection_type,
          provider_name=excluded.provider_name,
          command_template=excluded.command_template,
          base_url=excluded.base_url,
          api_key_required=excluded.api_key_required,
          cloud_data_consent=excluded.cloud_data_consent,
          local_only=excluded.local_only,
          enabled=excluded.enabled,
          last_test_status=excluded.last_test_status,
          last_test_message=excluded.last_test_message,
          updated_at=excluded.updated_at
        """,
        (
            row["id"], row["display_name"], row["connection_type"], row["provider_name"], row["command_template"], row["base_url"],
            row["api_key_required"], row["cloud_data_consent"], row["local_only"], row["enabled"], "saved", "OCR 连接已保存", now, now,
        ),
    )
    saved = db.one("SELECT * FROM ocr_connections WHERE id=?", (row["id"],))
    return public_ocr_connection(saved or row)


def _run_tesseract(path: Path) -> tuple[str, str]:
    executable = shutil.which("tesseract")
    if not executable:
        return "", "未发现 Tesseract。"
    with tempfile.TemporaryDirectory() as tmp:
        output_base = str(Path(tmp) / "ocr")
        completed = subprocess.run([executable, str(path), output_base, "-l", "chi_sim+eng"], capture_output=True, text=True, timeout=60, check=False)
        text_path = Path(f"{output_base}.txt")
        text = text_path.read_text(encoding="utf-8", errors="replace").strip() if text_path.exists() else ""
        if completed.returncode != 0 and not text:
            return "", completed.stderr.strip() or "Tesseract OCR 未识别成功。"
        return text, "Tesseract 本地 OCR 已完成" if text else "Tesseract 未识别到文字"


def _run_local_command(template: str, path: Path) -> tuple[str, str]:
    command = [str(path) if part == "{image}" else part for part in shlex.split(template)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    text = completed.stdout.strip()
    if completed.returncode != 0 and not text:
        return "", completed.stderr.strip() or "自定义 OCR 命令执行失败"
    return text, "自定义本地 OCR 已完成" if text else "自定义本地 OCR 未识别到文字"


def _run_http(row: dict[str, Any], path: Path) -> tuple[str, str]:
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    headers = {"Content-Type": "application/json"}
    key = load_provider_key(provider_key(str(row["id"])))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        str(row["base_url"]),
        data=json.dumps({"image_base64": image_b64, "filename": path.name}, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        context = verified_ssl_context() if str(row["connection_type"]) == "cloud_api" else None
        with urllib.request.urlopen(request, timeout=90, context=context) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = str(body.get("text") or body.get("result") or body.get("content") or "").strip()
        return text, "OCR 服务已完成" if text else "OCR 服务未返回文字"
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return "", f"OCR 服务调用失败：{exc}"


def extract_image_text(db: Database, path: Path) -> dict[str, Any]:
    selected = str(db.setting("selected_ocr_connection_id", "") or "")
    row = db.one("SELECT * FROM ocr_connections WHERE id=? AND enabled=1", (selected,)) if selected else None
    if row:
        try:
            if row["connection_type"] == "local_command":
                text, note = _run_local_command(str(row["command_template"]), path)
            else:
                if row["connection_type"] == "local_http":
                    validate_local_url(str(row["base_url"]))
                text, note = _run_http(row, path)
            return {
                "text": text,
                "note": note,
                "provider": row["display_name"],
                "data_location": "cloud" if row["connection_type"] == "cloud_api" else "local",
                "requires_consent": row["connection_type"] == "cloud_api",
            }
        except (ProviderError, LocalModelError, subprocess.TimeoutExpired) as exc:
            return {"text": "", "note": f"自定义 OCR 暂不可用：{exc}", "provider": row["display_name"], "data_location": "local", "requires_consent": False}
    text, note = _run_tesseract(path)
    return {"text": text, "note": note if text else f"{note} 可手动补文字，或在能力设置中接入自己的 OCR。", "provider": "Tesseract" if shutil.which("tesseract") else "manual", "data_location": "local", "requires_consent": False}
