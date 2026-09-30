#!/usr/bin/env python3
"""Import a legacy project's provider configuration without copying secrets.

Secret values go directly from the legacy .env into the operating-system
credential store. Only provider names, model names and consent flags are written
to OpenAvatar's SQLite database. The script never prints secret values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openavatar.config import ensure_directories, load_settings  # noqa: E402
from openavatar.db import Database  # noqa: E402
from openavatar.providers import store_provider_key  # noqa: E402


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely import legacy API configuration into OpenAvatar Studio")
    parser.add_argument("--legacy-env", type=Path, default=ROOT.parent / "旧数字人" / ".env")
    args = parser.parse_args()
    if not args.legacy_env.is_file():
        raise SystemExit(f"Legacy configuration not found: {args.legacy_env}")

    env = read_env(args.legacy_env)
    imported: list[str] = []
    if env.get("DEEPSEEK_API_KEY"):
        store_provider_key("chat", env["DEEPSEEK_API_KEY"])
        imported.append("chat")
    aliyun_key = env.get("DASHSCOPE_API_KEY") or env.get("ALIYUN_API_KEY")
    if aliyun_key:
        store_provider_key("aliyun", aliyun_key)
        imported.append("aliyun")
    if env.get("KIMI_API_KEY"):
        store_provider_key("kimi", env["KIMI_API_KEY"])
        imported.append("kimi")

    settings = load_settings()
    ensure_directories(settings)
    db = Database(settings.database_path)
    db.initialize()
    db.set_setting("model", {
        "mode": "cloud",
        "provider_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": env.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
        "cloud_data_consent": True,
        "ollama_url": settings.ollama_url,
        "ollama_model": settings.ollama_model,
    })
    db.set_setting("cloud_services", {
        "voice_clone_model": env.get("ALIYUN_VOICE_CLONE_MODEL") or "qwen-voice-enrollment",
        "voice_target_model": env.get("ALIYUN_VOICE_TARGET_MODEL") or "qwen3-tts-vc-2026-01-22",
        "voice_tts_model": env.get("ALIYUN_TTS_MODEL") or "qwen3-tts-vc-2026-01-22",
        "image_reference_model": env.get("QWEN_IMAGE_REFERENCE_MODEL") or env.get("QWEN_IMAGE_MODEL") or "qwen-image-2.0-pro",
        "video_model": env.get("WAN_VIDEO_MODEL") or env.get("VIDEO_GEN_MODEL") or "wan2.7-i2v-2026-04-25",
        "cloud_data_consent": True,
    })
    print("Imported credential types: " + (", ".join(imported) if imported else "none"))
    print("Secret values were stored in the operating-system credential store and were not copied into project files.")


if __name__ == "__main__":
    main()
