"""Collect installed-package notices and native runtime notices for binary releases."""
from __future__ import annotations

import ast
import importlib.metadata as metadata
import json
import platform
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = ROOT / 'build' / 'THIRD_PARTY_LICENSES'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    inventory = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get('Name', '').lower()):
        name = dist.metadata.get('Name', 'unknown')
        folder = target / re.sub(r'[^A-Za-z0-9_.-]', '_', f'{name}-{dist.version}')
        found = []
        for path in dist.files or []:
            if not any(word in Path(str(path)).name.lower() for word in ('license', 'copying', 'notice', 'copyright')):
                continue
            source = Path(dist.locate_file(path))
            if not source.is_file() or source.suffix.lower() in {'.py', '.pyc', '.so', '.pyd'}:
                continue
            folder.mkdir(exist_ok=True)
            filename = str(path).replace('/', '__').replace('\\', '__')
            shutil.copyfile(source, folder / filename)
            found.append(filename)
        inventory.append({'name': name, 'version': dist.version, 'license': dist.metadata.get('License-Expression') or dist.metadata.get('License'), 'files': found, 'project_urls': dist.metadata.get_all('Project-URL', [])})
    # Python binary distributions do not consistently include LICENSE on disk.
    sources = {
        'Python-LICENSE.txt': f'https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE',
        'OpenSSL-LICENSE.txt': f'https://raw.githubusercontent.com/openssl/openssl/openssl-{ssl.OPENSSL_VERSION.split()[1]}/LICENSE.txt',
        'Tcl-license.terms': 'https://raw.githubusercontent.com/tcltk/tcl/core-8-6-16/license.terms',
        'Tk-license.terms': 'https://raw.githubusercontent.com/tcltk/tk/core-8-6-16/license.terms',
        'zlib-LICENSE.txt': 'https://raw.githubusercontent.com/madler/zlib/v1.3.1/LICENSE',
        'bzip2-LICENSE.txt': 'https://sourceware.org/git/?p=bzip2.git;a=blob_plain;f=LICENSE;hb=bzip2-1.0.8',
        'libffi-LICENSE.txt': 'https://raw.githubusercontent.com/libffi/libffi/v3.4.8/LICENSE',
    }
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    for filename, url in sources.items():
        with urllib.request.urlopen(url, timeout=60, context=context) as response:
            content = response.read()
        if len(content) < 100 or b'<html' in content[:500].lower():
            raise RuntimeError(f'Invalid notice from {url}')
        (target / filename).write_bytes(content)
    (target / 'SQLite-NOTICE.txt').write_text('SQLite is in the public domain. Source and notice: https://sqlite.org/copyright.html\n', encoding='utf-8')
    if sys.platform == 'linux':
        native = target / 'linux-system-libraries'
        native.mkdir()
        paths = set()
        def walk(value):
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
            elif isinstance(value, str) and value.startswith('/') and '.so' in value:
                paths.add(value)
        for toc in (ROOT / 'build').rglob('COLLECT-*.toc'):
            walk(ast.literal_eval(toc.read_text()))
        for path in sorted(paths):
            result = subprocess.run(['dpkg-query', '-S', path], capture_output=True, text=True)
            if result.returncode:
                result = subprocess.run(['dpkg-query', '-S', str(Path(path).resolve())], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                package = line.split(': ', 1)[0].split(':')[0]
                notice = Path('/usr/share/doc') / package / 'copyright'
                if notice.is_file():
                    shutil.copyfile(notice, native / f'{package}-copyright.txt')
        common = Path('/usr/share/common-licenses')
        if common.exists():
            shutil.copytree(common, native / 'common-licenses')
    (target / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / 'SOURCES.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
    (target / 'README.txt').write_text('Third-party notices for OpenAvatar Studio binary distributions.\nThe inventory includes the build environment; some listed packages are build/test tools and are not shipped as runtime code. Pillow and other package notices also cover bundled native libraries.\nPython source: https://www.python.org/downloads/source/\nNative components retain their respective licenses; the project Apache-2.0 license does not replace them.\n', encoding='utf-8')
    print(f'Collected notices for {len(inventory)} installed distributions.')


if __name__ == '__main__':
    main()
