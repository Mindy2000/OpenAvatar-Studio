from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def pyinstaller_available() -> bool:
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError:
        return False


def build_command(name: str = "OpenAvatar Studio") -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        name,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--collect-all",
        "keyring",
        "--add-data",
        f"{ROOT / 'LICENSE'}{';' if platform.system() == 'Windows' else ':'}.",
        "--add-data",
        f"{ROOT / 'openavatar' / 'static'}{';' if platform.system() == 'Windows' else ':'}openavatar/static",
        "--add-data",
        f"{ROOT / 'openavatar' / 'i18n'}{';' if platform.system() == 'Windows' else ':'}openavatar/i18n",
        "--add-data",
        f"{ROOT / 'docs' / 'templates'}{';' if platform.system() == 'Windows' else ':'}docs/templates",
        str(ROOT / "openavatar" / "desktop.py"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OpenAvatar Studio desktop bundle with free tooling.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the command.")
    args = parser.parse_args()
    command = build_command()
    if args.dry_run:
        print(" ".join(command))
        return 0
    if not pyinstaller_available():
        print("未安装 PyInstaller。可运行：")
        print(f"{sys.executable} -m pip install pyinstaller")
        print("然后重新运行：")
        print(f"{sys.executable} scripts/build_desktop.py")
        return 2
    subprocess.run(command, cwd=ROOT, check=True)
    print("桌面应用构建完成，输出目录：dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
