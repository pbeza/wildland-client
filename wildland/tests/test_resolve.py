# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# pylint: disable=missing-docstring,redefined-outer-name

from pathlib import PurePosixPath
import os
import shutil
import json
import yaml

import pytest

from ..manifest.loader import ManifestLoader
from ..storage.local import LocalStorage
from ..resolve import WildlandPath, PathError, Search


## Path


def test_path_from_str():
    wlpath = WildlandPath.from_str(':/foo/bar:')
    assert wlpath.signer is None
    assert wlpath.parts == [PurePosixPath('/foo/bar')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux:')
    assert wlpath.signer == '0xabcd'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux:/some/file.txt')
    assert wlpath.signer == '0xabcd'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path == PurePosixPath('/some/file.txt')


def test_path_from_str_fail():
    with pytest.raises(PathError, match='has to start with signer'):
        WildlandPath.from_str('/foo/bar')

    with pytest.raises(PathError, match='Unrecognized signer field'):
        WildlandPath.from_str('foo:/foo/bar:')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar:')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar:baz.txt')

    with pytest.raises(PathError, match='Path has no containers'):
        WildlandPath.from_str('0xabcd:')

    with pytest.raises(PathError, match='Path has no containers'):
        WildlandPath.from_str('0xabcd:/foo')


def test_path_to_str():
    wlpath = WildlandPath('0xabcd', [PurePosixPath('/foo/bar')], None)
    assert str(wlpath) == '0xabcd:/foo/bar:'

    wlpath = WildlandPath(
        None, [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')], None)
    assert str(wlpath) == ':/foo/bar:/baz/quux:'

    wlpath = WildlandPath(
        None,
        [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')],
        PurePosixPath('/some/file.txt'))
    assert str(wlpath) == ':/foo/bar:/baz/quux:/some/file.txt'


## Path resolution

@pytest.fixture
def setup(base_dir, cli):
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/path')
    cli('storage', 'create', 'local', 'Storage1',
        '--path', base_dir / 'storage1',
        '--container', 'Container1')

    cli('container', 'create', 'Container2',
        '--path', '/path/subpath',
        '--path', '/other/path')
    cli('storage', 'create', 'local', 'Storage2',
        '--path', base_dir / 'storage2',
        '--container', 'Container2')

    os.mkdir(base_dir / 'storage1/other/')
    # TODO copy storage manifest as well
    # (and make sure storage manifests are resolved in the local context)
    shutil.copyfile(base_dir / 'containers/Container2.yaml',
                    base_dir / 'storage1/other/path.yaml')


@pytest.fixture
def loader(setup, base_dir):
    # pylint: disable=unused-argument
    loader = ManifestLoader(base_dir=base_dir)
    try:
        loader.load_users()
        yield loader
    finally:
        loader.close()


def test_resolve_first(base_dir, loader):
    search = Search(loader, WildlandPath.from_str(':/path:'), '0xaaa')
    search.resolve_first()
    assert search.steps[0].container_path == PurePosixPath('/path')

    storage = search.find_storage()
    assert isinstance(storage, LocalStorage)
    assert storage.root == base_dir / 'storage1'

    search = Search(loader, WildlandPath.from_str(':/path/subpath:'), '0xaaa')
    search.resolve_first()
    assert search.steps[0].container_path == PurePosixPath('/path/subpath')

    storage = search.find_storage()
    assert isinstance(storage, LocalStorage)
    assert storage.root == base_dir / 'storage2'


def test_read_file(base_dir, loader):
    with open(base_dir / 'storage1/file.txt', 'w') as f:
        f.write('Hello world')
    search = Search(loader, WildlandPath.from_str(':/path:/file.txt'), '0xaaa')
    data = search.read_file()
    assert data == b'Hello world'


def test_write_file(base_dir, loader):
    search = Search(loader, WildlandPath.from_str(':/path:/file.txt'), '0xaaa')
    search.write_file(b'Hello world')
    with open(base_dir / 'storage1/file.txt') as f:
        assert f.read() == 'Hello world'


def test_read_file_traverse(base_dir, loader):
    with open(base_dir / 'storage2/file.txt', 'w') as f:
        f.write('Hello world')
    search = Search(loader, WildlandPath.from_str(':/path:/other/path:/file.txt'), '0xaaa')
    data = search.read_file()
    assert data == b'Hello world'


def test_verify_traverse(cli, loader):
    # pylint: disable=unused-argument
    cli('container', 'verify', ':/path:/other/path:')


def test_mount_traverse(cli, loader, base_dir):
    # pylint: disable=unused-argument
    with open(base_dir / 'mnt/.control/paths', 'w') as f:
        json.dump({}, f)
    cli('container', 'mount', ':/path:/other/path:')


def test_unmount_traverse(cli, loader, base_dir):
    # pylint: disable=unused-argument
    with open(base_dir / 'containers/Container2.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    with open(base_dir / 'mnt/.control/paths', 'w') as f:
        json.dump({
            f'/.users/0xaaa{path}': [101],
        }, f)
    cli('container', 'unmount', ':/path:/other/path:')
