from openavatar.services import ocr


def test_windows_ocr_preserves_backslashes_and_quoted_spaces(monkeypatch):
    monkeypatch.setattr(ocr.platform, 'system', lambda: 'Windows')
    assert ocr.split_local_command(r'"C:\Program Files\Python\python.exe" "C:\OCR tools\read.py" {image}') == [
        r'C:\Program Files\Python\python.exe', r'C:\OCR tools\read.py', '{image}',
    ]


def test_posix_ocr_preserves_quoted_spaces(monkeypatch):
    monkeypatch.setattr(ocr.platform, 'system', lambda: 'Darwin')
    assert ocr.split_local_command('"/Applications/OCR tools/read" {image}') == ['/Applications/OCR tools/read', '{image}']


def test_desktop_starts_without_console_streams(tmp_path):
    import os
    import subprocess
    import sys

    # Windows PyInstaller --windowed sets stdout and stderr to None.
    code = """
import sys
sys.stdout = None
sys.stderr = None
from openavatar.desktop import runtime_from_args, start_server, wait_until_ready
runtime = runtime_from_args(18767)
server = start_server(runtime)
try:
    assert wait_until_ready(runtime)
finally:
    server.should_exit = True
"""
    subprocess.run([sys.executable, '-c', code], env={**os.environ, 'OPENAVATAR_DATA_DIR': str(tmp_path)}, check=True, timeout=30)
