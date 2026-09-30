"""Verify the distributable archive, then launch its extracted application."""
import hashlib
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def main():
    archives = list((ROOT / 'release').glob('*.zip'))
    assert len(archives) == 1, archives
    archive = archives[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive.with_suffix('.zip.sha256').read_text().split()[0]
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        names = zipped.namelist()
        assert 'THIRD_PARTY_LICENSES/inventory.json' in names
        assert 'LICENSE' in names and 'INSTALL.txt' in names
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            assert not path.is_absolute() and '..' not in path.parts, item.filename
            assert path.suffix not in {'.sqlite', '.db', '.openavatar.zip'}, item.filename
            assert '.env' not in path.parts and 'demo_assets' not in path.parts, item.filename
            assert not path.name.startswith('libreadline'), item.filename
            if stat.S_ISLNK(item.external_attr >> 16):
                link = zipped.read(item).decode()
                assert not os.path.isabs(link), item.filename
                resolved = os.path.normpath(str(path.parent / link))
                assert not resolved.startswith('..'), item.filename
            # Only project text assets: dependency test data can contain fake credential fixtures.
            if '/openavatar/' in item.filename and path.suffix in {'.js', '.json', '.html', '.css'}:
                data = zipped.read(item)
                assert not re.search(rb'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,})', data), item.filename
    with tempfile.TemporaryDirectory(prefix='openavatar-extracted-') as temporary:
        if platform.system() == 'Darwin':
            subprocess.run(['ditto', '-x', '-k', str(archive), temporary], check=True)
        elif platform.system() == 'Linux':
            subprocess.run(['unzip', '-q', str(archive), '-d', temporary], check=True)
        else:
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(temporary)
        subprocess.run([sys.executable, str(ROOT / 'scripts/check_desktop_bundle.py'), '--dist', temporary], check=True)
    print(f'RELEASE_ARCHIVE_OK {archive.name}')


if __name__ == '__main__':
    main()
