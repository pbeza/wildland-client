# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Pawel Peregud <pepesza@wildland.io>
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=missing-docstring,redefined-outer-name,consider-using-with
from pathlib import Path
import os
import time
import subprocess
import uuid
import zlib
import errno

import pytest

from wildland.storage_backends.local import LocalStorageBackend
from wildland.wildland_object.wildland_object import WildlandObject
from wildland.client import Client
from wildland.cli.cli_base import ContextObj
from wildland.cli.cli_main import _do_mount_containers

# Pylint does not recognize imported pytest fixtures as used.
# It cannot be moved to the local conftest.py because import from one conftest.py to another fails.
from wildland.tests.conftest import cli, base_dir  # pylint: disable=unused-import
from ..backend import EncFS, GoCryptFS, generate_password


@pytest.mark.parametrize('engine', ['gocryptfs', 'encfs'])
def test_encrypted_with_url(cli, base_dir, engine):
    local_dir = base_dir / 'local'
    Path(local_dir).mkdir()
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', local_dir,
        '--container', 'referenceContainer', '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    # handle both files and paths here
    reference_url = 'wildland::/reference_PATH:'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'encrypted', 'ProxyStorage',
        '--reference-container-url', reference_url,
        '--engine', engine,
        '--container', 'Container', '--inline')

    client = Client(base_dir)

    obj = ContextObj(client)
    obj.fs_client = client.fs_client

    # But select_storage loads also the reference manifest
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'encrypted'
    assert storage.params['symmetrickey']
    assert storage.params['engine'] in ['gocryptfs', 'encfs']
    reference_storage = storage.params['storage']
    assert isinstance(reference_storage, dict)
    assert reference_storage['type'] == 'local'

    # start and check if engine is running
    user = client.users['0xaaa']
    client.fs_client.start(single_thread=False, default_user=user)
    to_mount = ['Container']
    _do_mount_containers(obj, to_mount)
    subprocess.run(['pidof', engine], check=True)

    # write and read a file
    mounted_plaintext = obj.fs_client.mount_dir / Path('/PATH').relative_to('/')
    assert os.listdir(mounted_plaintext) == ['.manifest.wildland.yaml'], \
        "plaintext dir should contain pseudomanifest only!"
    with open(mounted_plaintext / 'test.file', 'w') as ft:
        ft.write("1" * 10000)  # low entropy plaintext file

    assert sorted(os.listdir(mounted_plaintext)) == ['.manifest.wildland.yaml', 'test.file']

    time.sleep(5)  # time to let engine finish writing to plaintext dir

    # check if ciphertext directory looks familiar
    listing = os.listdir(local_dir)
    assert len(listing) > 1
    listing_set = set(listing) - {'gocryptfs.conf', 'gocryptfs.diriv', '.encfs6.xml'}
    listing = list(listing_set)

    # read and examine entropy of ciphertext file
    with open(local_dir / listing[0], 'rb') as fb:
        enc_bytes = fb.read()
    packed_bytes = zlib.compress(enc_bytes)
    assert len(packed_bytes) * 1.05 > len(enc_bytes), "encrypted bytes are of low entropy!"

    # kill engine and check if attempt to write will leak the plaintext
    ft2 = open(mounted_plaintext / 'leak.test', 'w')

    if engine == 'gocryptfs':
        subprocess.run(['pkill gocryptfs'], shell=True, check=True)
        time.sleep(1)
        with pytest.raises(OSError) as e:
            ft2.write("2" * 10000)
        assert e.value.errno == errno.EINVAL
    elif engine == 'encfs':
        subprocess.run(['pkill --signal 9 encfs'], shell=True, check=True)
        time.sleep(1)
        with pytest.raises(OSError):
            ft2.write("2" * 10000)

    time.sleep(10)  # otherwise "unmount: /tmp/.../mnt: target is busy"


def test_gocryptfs_runner(base_dir):
    first, _first_clear, first_enc = _make_dirs(base_dir, 'a')
    second, second_clear, second_enc = _make_dirs(base_dir, 'b')

    # init, capture config
    runner = GoCryptFS.init(first, first_enc, None)

    # open for writing, working directory
    runner2 = GoCryptFS(second, second_enc, runner.credentials())
    params = {'location': second_enc,
              'type': 'local',
              'backend-id': str(uuid.uuid4())
              }
    runner2.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'w') as f:
        f.write("string")
    assert runner2.stop() == 0

    assert not (second_clear / 'test.file').exists()

    # open for reading, working directory
    runner3 = GoCryptFS(second, second_enc, runner.credentials())
    assert runner3.password
    assert runner3.config
    assert runner3.topdiriv
    runner3.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'r') as f:
        assert f.read() == "string"
    assert runner3.stop() == 0


def _make_dirs(base_dir, dir_name):
    base = base_dir / dir_name
    clear = base / 'clear'
    enc = base / 'enc'
    base.mkdir()
    clear.mkdir()
    enc.mkdir()
    return base, clear, enc


def test_encfs_runner(base_dir):
    first, first_clear, first_enc = _make_dirs(base_dir, 'a')
    second, second_clear, second_enc = _make_dirs(base_dir, 'b')

    # init, capture config
    runner = EncFS.init(first, first_enc, first_clear)

    # open for writing, working directory
    runner2 = EncFS(second, second_enc, runner.credentials())
    params = {'location': second_enc,
              'type': 'local',
              'backend-id': str(uuid.uuid4())
              }
    runner2.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'w') as f:
        f.write("string")
    assert runner2.stop() == 0

    assert not (second_clear / 'test.file').exists()

    # open for reading, working directory
    runner3 = EncFS(second, second_enc, runner.credentials())
    assert runner3.password
    assert runner3.config
    runner3.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'r') as f:
        assert f.read() == "string"
    assert runner3.stop() == 0


def test_generate_password():
    assert ';' not in generate_password(100)
