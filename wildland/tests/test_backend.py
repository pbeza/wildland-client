# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument

import os
import time
from typing import Callable, List, Tuple
from pathlib import PurePosixPath, Path
from unittest.mock import patch

import pytest

from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.base import StorageBackend
from ..storage_backends.watch import FileEvent


@pytest.fixture(params=[LocalStorageBackend])
def storage_backend(request) -> Callable:
    '''
    Parametrize the tests by storage backend; at the moment include only those with watchers
    implemented.
    '''

    return request.param


@pytest.fixture
def cleanup():
    cleanup_functions = []

    def add_cleanup(func):
        cleanup_functions.append(func)

    yield add_cleanup

    for f in cleanup_functions:
        f()


def make_storage(location, backend_class) -> Tuple[StorageBackend, Path]:
    storage_dir = location / 'storage1'
    os.mkdir(storage_dir)
    backend = backend_class(params={'path': storage_dir, 'type': getattr(backend_class, 'TYPE')})
    return backend, storage_dir


# Local

def test_simple_operations(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    backend.mkdir(PurePosixPath('newdir'), mode=0o777)
    assert (storage_dir / 'newdir').exists()

    file = backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT, mode=0o777)
    file.release(os.O_RDWR)
    assert (storage_dir / 'newdir/testfile').exists()

    file = backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR)
    file.write(b'aaaa', 0)
    file.release(os.O_RDWR)

    with open(storage_dir / 'newdir/testfile') as file:
        assert file.read() == 'aaaa'

    backend.unlink(PurePosixPath('newdir/testfile'))
    assert not (storage_dir / 'newdir/testfile').exists()

    backend.rmdir(PurePosixPath('newdir'))
    assert not (storage_dir / 'newdir').exists()


def test_watcher_not_ignore_own(tmpdir, storage_backend, cleanup):
    backend, _ = make_storage(tmpdir, storage_backend)

    received_events: List[FileEvent] = []

    backend.start_watcher(handler=received_events.extend, ignore_own_events=False)
    cleanup(backend.stop_watcher)

    backend.mkdir(PurePosixPath('newdir'), mode=0o777)

    time.sleep(1)
    assert received_events == [FileEvent('create', PurePosixPath('newdir'))]
    received_events.clear()

    with backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT, mode=0o777):
        pass

    time.sleep(1)
    assert received_events == [FileEvent('create', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    with backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    time.sleep(1)
    assert received_events == [FileEvent('modify', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.unlink(PurePosixPath('newdir/testfile'))

    time.sleep(1)
    assert received_events == [FileEvent('delete', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.rmdir(PurePosixPath('newdir'))

    time.sleep(1)
    assert received_events == [FileEvent('delete', PurePosixPath('newdir'))]


def test_watcher_ignore_own(tmpdir, storage_backend, cleanup):
    backend, _ = make_storage(tmpdir, storage_backend)

    received_events: List[FileEvent] = []

    watcher = backend.start_watcher(handler=received_events.extend, ignore_own_events=True)
    cleanup(backend.stop_watcher)

    backend.mkdir(PurePosixPath('newdir'), mode=0o777)
    time.sleep(1)

    with backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT, mode=0o777):
        pass

    with backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    backend.unlink(PurePosixPath('newdir/testfile'))

    backend.rmdir(PurePosixPath('newdir'))

    time.sleep(2)

    assert received_events == []
    assert watcher.ignore_list == []

    # perform some external operations
    os.mkdir(tmpdir / 'storage1/anotherdir')

    time.sleep(2)

    assert received_events == [FileEvent('create', PurePosixPath('anotherdir'))]


def test_hashing_short(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('aaaa')

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'


def test_hashing_long(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    with open(storage_dir / 'testfile', mode='w') as f:
        for _ in range(1024 ** 2):
            f.write('aaaa')

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '299285fc41a44cdb038b9fdaf494c76ca9d0c866672b2b266c1a0c17dda60a05'


def test_hash_cache(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('aaaa')

    time.sleep(1)

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'

    with patch('wildland.storage_backends.base.StorageBackend.get_hash'):
        # if the hash did not get cached correctly, this will return a mock not the correct hash
        assert backend.get_hash(PurePosixPath("testfile")) == \
               '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('bbbb')

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '81cc5b17018674b401b42f35ba07bb79e211239c23bffe658da1577e3e646877'


def test_walk(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    os.mkdir(storage_dir / 'dir1')
    os.mkdir(storage_dir / 'dir2')
    os.mkdir(storage_dir / 'dir1/subdir1')
    os.mkdir(storage_dir / 'dir1/subdir2')
    os.mkdir(storage_dir / 'dir1/subdir1/subsubdir1')

    open(storage_dir / 'testfile1', 'a').close()
    open(storage_dir / 'dir2/testfile2', 'a').close()
    open(storage_dir / 'dir1/subdir1/testfile3', 'a').close()
    open(storage_dir / 'dir1/subdir1/testfile4', 'a').close()
    open(storage_dir / 'dir1/subdir1/subsubdir1/testfile5', 'a').close()

    received_files = [(str(f[0]), f[1].is_dir()) for f in backend.walk()]
    expected_files = [('dir1', True),
                      ('dir2', True),
                      ('dir1/subdir1', True),
                      ('dir1/subdir2', True),
                      ('dir1/subdir1/subsubdir1', True),
                      ('testfile1', False),
                      ('dir2/testfile2', False),
                      ('dir1/subdir1/testfile3', False),
                      ('dir1/subdir1/testfile4', False),
                      ('dir1/subdir1/subsubdir1/testfile5', False)]

    assert sorted(received_files) == sorted(expected_files)
