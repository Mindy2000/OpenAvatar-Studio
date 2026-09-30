import hashlib
import os
import stat
import sys
import zipfile

import pytest

from scripts import package_release


@pytest.mark.parametrize(('machine', 'arch'), [('x86_64', 'x64'), ('arm64', 'arm64')])
def test_release_architecture_names_and_checksums(tmp_path, monkeypatch, machine, arch):
    bundle = tmp_path / 'dist' / 'OpenAvatar Studio.app'
    bundle.mkdir(parents=True)
    (bundle / 'test.txt').write_text('test bundle')
    if os.name != 'nt':
        (bundle / 'linked.txt').symlink_to('test.txt')
    notices = tmp_path / 'build' / 'THIRD_PARTY_LICENSES'
    notices.mkdir(parents=True)
    (notices / 'inventory.json').write_text('[]')
    (tmp_path / 'LICENSE').write_text('test license')
    monkeypatch.setattr(package_release, 'ROOT', tmp_path)
    monkeypatch.setattr(package_release.platform, 'machine', lambda: machine)
    monkeypatch.setattr(sys, 'argv', ['package_release.py', '--version', 'test', '--platform', 'macos', '--arch', arch])
    assert package_release.main() == 0
    archive = tmp_path / 'release' / f'OpenAvatar-Studio-test-macos-{arch}.zip'
    assert archive.is_file()
    assert archive.with_suffix('.zip.sha256').read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read('OpenAvatar Studio.app/test.txt') == b'test bundle'
        assert zipped.read('THIRD_PARTY_LICENSES/inventory.json') == b'[]'
        if os.name != 'nt':
            link = zipped.getinfo('OpenAvatar Studio.app/linked.txt')
            assert stat.S_ISLNK(link.external_attr >> 16)
            assert zipped.read(link) == b'test.txt'


def test_cannot_label_arm_build_as_intel(monkeypatch):
    monkeypatch.setattr(package_release.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(sys, 'argv', ['package_release.py', '--version', 'test', '--arch', 'x64'])
    with pytest.raises(SystemExit, match='architecture mismatch'):
        package_release.main()


def test_release_version_matches_embedded_application():
    from openavatar import __version__
    from scripts.check_release_version import validate_version
    validate_version('v' + __version__)
    validate_version('preview')
    with pytest.raises(ValueError, match='does not match'):
        validate_version('v0.0.0-wrong-version')
