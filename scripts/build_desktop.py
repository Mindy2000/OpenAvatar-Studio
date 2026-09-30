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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build OpenAvatar Studio desktop bundle with free tooling.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the command.")
    args = parser.parse_args()
    command = build_command()
    if args.dry_run:
        print(" ".join(command))
        return 0
    if not pyinstaller_available():
        print("PyInstaller is not installed. Run:")
        print(f"{sys.executable} -m pip install pyinstaller")
        print("Then run:")
        print(f"{sys.executable} scripts/build_desktop.py")
        return 2
    subprocess.run(command, cwd=ROOT, check=True)
    print("Desktop build complete. Output directory: dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
