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


def test_startup_failure_does_not_show_running_window(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from openavatar import desktop
    server = SimpleNamespace(should_exit=False)
    runtime = desktop.DesktopRuntime('127.0.0.1', 8767, 'http://127.0.0.1:8767', tmp_path)
    monkeypatch.setattr(desktop, 'runtime_from_args', lambda port: runtime)
    monkeypatch.setattr(desktop, 'start_server', lambda runtime: server)
    monkeypatch.setattr(desktop, 'wait_until_ready', lambda *args, **kwargs: False)
    seen = []
    monkeypatch.setattr(desktop, 'show_startup_error', lambda: seen.append('error'))
    monkeypatch.setattr(desktop, 'run_tk_window', lambda *args: seen.append('window'))
    monkeypatch.setattr(desktop, 'open_browser', lambda *args: seen.append('browser'))
    assert desktop.main([]) == 1
    assert seen == ['error']
    assert server.should_exit


def test_readiness_rejects_unrelated_http_service(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from openavatar import desktop

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"unrelated": true}')

        def log_message(self, *args):
            pass

    with HTTPServer(('127.0.0.1', 0), Handler) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            port = http.server_port
            runtime = desktop.DesktopRuntime('127.0.0.1', port, f'http://127.0.0.1:{port}', tmp_path)
            assert not desktop.wait_until_ready(runtime, timeout=0.3)
        finally:
            http.shutdown()
            thread.join(timeout=2)
