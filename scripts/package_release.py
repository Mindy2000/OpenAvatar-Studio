from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def select_bundle(dist: Path, platform_name: str) -> Path:
    normalized = platform_name.lower().replace("darwin", "macos")
    preferred = dist / ("OpenAvatar Studio.app" if normalized == "macos" else "OpenAvatar Studio")
    if preferred.exists():
        return preferred
    candidates = [path for path in dist.iterdir() if path.is_dir() and (normalized != "macos" or path.suffix == ".app")]
    if len(candidates) == 1:
        return candidates[0]
    raise SystemExit(f"could not identify the {normalized} desktop bundle in dist/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a platform desktop build for GitHub Releases.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", default=platform.system().lower())
    host_arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    parser.add_argument("--arch", choices=["x64", "arm64"], default=host_arch)
    args = parser.parse_args()
    if args.arch != host_arch:
        raise SystemExit(f"architecture mismatch: requested {args.arch}, running on {host_arch}")

    dist = ROOT / "dist"
    if not dist.is_dir() or not any(dist.iterdir()):
        raise SystemExit("dist/ is empty; build the desktop application first")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    platform_name = args.platform.lower().replace("darwin", "macos")
    bundle = select_bundle(dist, platform_name)
    base_name = f"OpenAvatar-Studio-{args.version}-{platform_name}-{args.arch}"
    notices = ROOT / "build" / "THIRD_PARTY_LICENSES"
    if not (notices / "inventory.json").is_file():
        raise SystemExit("Missing release notices; run scripts/collect_release_licenses.py first")
    archive_path = release / f"{base_name}.zip"
    with tempfile.TemporaryDirectory(prefix="openavatar-package-") as temporary:
        staging = Path(temporary)
        shutil.copytree(bundle, staging / bundle.name, symlinks=True)
        shutil.copytree(notices, staging / "THIRD_PARTY_LICENSES")
        shutil.copyfile(ROOT / "LICENSE", staging / "LICENSE")
        (staging / "INSTALL.txt").write_text(
            f"OpenAvatar Studio {args.version} - desktop preview\n\n"
            "Extract the whole archive before launching. Keep all bundled files together.\n"
            "macOS: open OpenAvatar Studio.app. Windows: open OpenAvatar Studio/OpenAvatar Studio.exe.\n"
            "Linux: run OpenAvatar Studio/OpenAvatar Studio. Python is bundled.\n"
            "This preview is not developer-signed or notarized. Cloud services require your own API keys.\n"
            "FFmpeg, optional OCR engines and a Linux secret-service backend may require separate installation.\n"
            "Guide: https://github.com/Mindy2000/OpenAvatar-Studio/blob/main/docs/GUIDE_EN.md\n",
            encoding="utf-8",
        )
        if platform.system() == "Darwin":
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", str(staging), str(archive_path)], check=True)
        elif platform.system() == "Linux":
            subprocess.run(["zip", "-q", "-r", "-y", str(archive_path), "."], cwd=staging, check=True)
        else:
            shutil.make_archive(str(release / base_name), "zip", root_dir=staging)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum = release / f"{archive_path.name}.sha256"
    checksum.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    print(archive_path)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
