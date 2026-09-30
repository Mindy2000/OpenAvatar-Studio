from openavatar.services import ocr


def test_windows_ocr_preserves_backslashes_and_quoted_spaces(monkeypatch):
    monkeypatch.setattr(ocr.platform, 'system', lambda: 'Windows')
    assert ocr.split_local_command(r'"C:\Program Files\Python\python.exe" "C:\OCR tools\read.py" {image}') == [
        r'C:\Program Files\Python\python.exe', r'C:\OCR tools\read.py', '{image}',
    ]


def test_posix_ocr_preserves_quoted_spaces(monkeypatch):
    monkeypatch.setattr(ocr.platform, 'system', lambda: 'Darwin')
    assert ocr.split_local_command('"/Applications/OCR tools/read" {image}') == ['/Applications/OCR tools/read', '{image}']
