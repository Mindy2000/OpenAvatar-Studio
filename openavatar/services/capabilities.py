from __future__ import annotations

from typing import Any

from openavatar.db import Database
from openavatar.providers import ChatProvider, ProviderConfig, load_provider_key
from openavatar.services.ocr import detect_local_ocr


def capability_report(db: Database, model_config: ProviderConfig, model_client: ChatProvider) -> dict[str, Any]:
    model_available = model_client.available()
    selected_ocr = str(db.setting("selected_ocr_connection_id", "") or "")
    ocr_row = db.one("SELECT * FROM ocr_connections WHERE id=?", (selected_ocr,)) if selected_ocr else None
    detected_ocr = detect_local_ocr()
    cloud_services = db.setting("cloud_services", {})
    has_aliyun = bool(load_provider_key("aliyun"))
    has_north = bool(load_provider_key("north"))
    rows = [
        {
            "key": "chat",
            "name": "对话与人格分析",
            "status": "available" if model_available else "needs_setup",
            "running_at": "cloud" if model_config.mode in {"cloud", "cloud_openai"} else "local",
            "provider": model_config.provider_name,
            "sends": "人格摘要、相关记忆、近期对话和用户输入" if model_config.mode in {"cloud", "cloud_openai"} else "不发送到外部服务",
            "cost": "可能产生 API 费用" if model_config.mode in {"cloud", "cloud_openai"} else "消耗本机资源",
            "consent": bool(model_config.cloud_data_consent),
        },
        {
            "key": "ocr",
            "name": "截图 OCR",
            "status": "available" if ocr_row or any(item["id"] == "builtin_tesseract" for item in detected_ocr) else "manual",
            "running_at": "cloud" if ocr_row and ocr_row["connection_type"] == "cloud_api" else "local_or_manual",
            "provider": str(ocr_row["display_name"]) if ocr_row else next((item["display_name"] for item in detected_ocr if item["id"] != "manual"), "手动补文字"),
            "sends": "截图图片会发送给用户配置的 OCR API" if ocr_row and ocr_row["connection_type"] == "cloud_api" else "截图留在本机；没有 OCR 时可手动补文字",
            "cost": "可能产生 OCR API 费用" if ocr_row and ocr_row["connection_type"] == "cloud_api" else "免费或本机资源",
            "consent": bool(ocr_row.get("cloud_data_consent")) if ocr_row else False,
        },
        {
            "key": "asr",
            "name": "声音转写 ASR",
            "status": "manual",
            "running_at": "manual_or_provider",
            "provider": "手动确认或后续 ASR provider",
            "sends": "当前上传音频只保存本机；接入云端 ASR 后才会上传音频",
            "cost": "手动免费；云端 ASR 可能产生费用",
            "consent": False,
        },
        {
            "key": "voice_clone",
            "name": "声音复刻与 TTS",
            "status": "available" if has_aliyun else "needs_setup",
            "running_at": "cloud" if has_aliyun else "local_or_unconfigured",
            "provider": "阿里云百炼" if has_aliyun else "浏览器音色/未配置",
            "sends": "声音复刻上传授权音频；TTS 上传待播放文字" if has_aliyun else "未配置云端复刻时不上传音频",
            "cost": "可能产生 API 费用" if has_aliyun else "本地试听免费",
            "consent": bool(cloud_services.get("cloud_data_consent", False)),
        },
        {
            "key": "visual_generation",
            "name": "视觉身份与图片生成",
            "status": "available" if has_aliyun else "review_only",
            "running_at": "cloud" if has_aliyun else "local_review",
            "provider": "阿里云百炼" if has_aliyun else "本地审批流程",
            "sends": "参考图生成会上传用户批准的图片" if has_aliyun else "候选图只在本机保存和审批",
            "cost": "可能产生 API 费用" if has_aliyun else "免费",
            "consent": bool(cloud_services.get("cloud_data_consent", False)),
        },
        {
            "key": "video",
            "name": "实时视频通话 Avatar",
            "status": "available" if has_north else "needs_setup",
            "running_at": "cloud",
            "provider": "North/Atlas（固定 provider）",
            "sends": "创建通话时上传 HTTPS face URL 或 approved/canonical 身份参考图；通话音频轨道进入 LiveKit/North 实时口型链路",
            "cost": "North/Atlas 可能按通话时长计费",
            "consent": bool(cloud_services.get("cloud_data_consent", False)),
        },
        {"key": "memory", "name": "长期记忆与检索", "status": "available", "running_at": "local", "provider": "SQLite 本地库", "sends": "不发送到外部服务", "cost": "免费", "consent": True},
        {"key": "package", "name": "人物包导入导出", "status": "available", "running_at": "local", "provider": "OpenAvatar Package v2", "sends": "不上传；导入前本机预检", "cost": "免费", "consent": True},
        {"key": "proactive", "name": "主动联系", "status": "user_controlled", "running_at": "uses_chat_model", "provider": model_config.provider_name, "sends": "开启后会按当前对话模型的数据去向处理", "cost": "取决于当前模型连接", "consent": bool(model_config.cloud_data_consent)},
        {"key": "desktop", "name": "桌面应用与跨平台启动", "status": "packaging_ready", "running_at": "local", "provider": "Python Desktop Launcher + PyInstaller", "sends": "只启动本机服务，不上传数据", "cost": "免费工具链；未签名内测版可能有系统提示", "consent": True},
    ]
    return {"items": rows, "principle": "本地优先，每个能力独立配置；云端调用必须让用户知道发送内容、服务商和费用风险。"}
