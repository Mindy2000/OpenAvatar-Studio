from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {".txt", ".md", ".log"}
JSON_EXTENSIONS = {".json", ".jsonl"}
CSV_EXTENSIONS = {".csv", ".tsv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}


def safe_filename(name: str) -> str:
    clean = Path(name or "upload.bin").name
    clean = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", clean, flags=re.UNICODE)
    return clean[:120] or "upload.bin"


def strip_image_metadata(path: Path) -> bool:
    """Remove EXIF/GPS metadata from supported images while preserving pixels."""
    try:
        from PIL import Image
        with Image.open(path) as source:
            source.load()
            image = Image.new(source.mode, source.size)
            image.putdata(list(source.getdata()))
            save_format = source.format or ("PNG" if path.suffix.lower() == ".png" else "JPEG")
            options = {"quality": 95} if save_format.upper() in {"JPEG", "WEBP"} else {}
            image.save(path, format=save_format, **options)
        return True
    except (ImportError, OSError, ValueError):
        return False


def _flatten_json(payload: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    candidates = payload if isinstance(payload, list) else payload.get("messages", []) if isinstance(payload, dict) else []
    for item in candidates:
        if isinstance(item, str):
            rows.append({"speaker": "", "content": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        content = item.get("content", item.get("text", item.get("message", "")))
        if isinstance(content, list):
            content = " ".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        speaker = item.get("speaker", item.get("role", item.get("sender", item.get("name", ""))))
        if str(content).strip():
            rows.append({"speaker": str(speaker).strip(), "content": str(content).strip()})
    return rows


def _parse_text(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    speaker_pattern = re.compile(r"^\s*([^:：]{1,32})[:：]\s*(.+)$")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = speaker_pattern.match(line)
        if match:
            rows.append({"speaker": match.group(1).strip(), "content": match.group(2).strip()})
        else:
            rows.append({"speaker": "", "content": line})
    return rows


def parse_conversation(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    if suffix in JSON_EXTENSIONS:
        if suffix == ".jsonl":
            return [row for line in text.splitlines() if line.strip() for row in _flatten_json([json.loads(line)])]
        return _flatten_json(json.loads(text))
    if suffix in CSV_EXTENSIONS:
        dialect = "excel-tab" if suffix == ".tsv" else "excel"
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = []
        for item in reader:
            lowered = {str(k).lower(): v for k, v in item.items()}
            content = lowered.get("content") or lowered.get("text") or lowered.get("message") or ""
            speaker = lowered.get("speaker") or lowered.get("role") or lowered.get("sender") or ""
            if str(content).strip():
                rows.append({"speaker": str(speaker).strip(), "content": str(content).strip()})
        return rows
    if suffix in TEXT_EXTENSIONS:
        return _parse_text(text)
    raise ValueError("该文件不是可解析的聊天记录格式")


def category_for_suffix(suffix: str) -> str | None:
    suffix = suffix.lower()
    if suffix in TEXT_EXTENSIONS | JSON_EXTENSIONS | CSV_EXTENSIONS:
        return "conversation"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return None


def extract_image_text_locally(path: Path) -> tuple[str, str]:
    """Use optional local Tesseract. Never sends the image over the network."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return "", "图片已保存在本机；安装 Pillow、pytesseract 和 Tesseract 后可启用本地 OCR。"
    try:
        text = pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng").strip()
        return text, "本地 OCR 已完成" if text else "本地 OCR 未识别到文字"
    except Exception as exc:
        return "", f"本地 OCR 暂不可用：{exc}"
