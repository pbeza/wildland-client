# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=missing-docstring,redefined-outer-name
from pathlib import Path, PurePosixPath
import os
from datetime import datetime
import uuid

import pytest

from wildland.wildland_object.wildland_object import WildlandObject
from .helpers import treewalk
from ..client import Client
from ..manifest.manifest import Manifest
from ..utils import yaml_parser


def test_timeline_with_url(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', '/tmp/local-path',
        '--container', 'referenceContainer', '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    reference_url = f'file://{reference_path}'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'timeline', 'ProxyStorage',
        '--reference-container-url', reference_url,
        '--container', 'Container', '--no-inline')

    client = Client(base_dir)

    # When loaded directly, the storage manifest contains container URL...
    storage = client.load_object_from_name(WildlandObject.Type.STORAGE, 'ProxyStorage')
    assert storage.params['reference-container'] == reference_url

    # But select_storage loads also the reference manifest
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'timeline'
    reference_storage = storage.params['storage']
    assert isinstance(reference_storage, dict)
    assert reference_storage['type'] == 'local'


@pytest.fixture
def data_dir(base_dir):
    data_dir = Path(base_dir / 'data')
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def storage(data_dir):
    return {
        'timeline-root': '/timeline',
        'reference-container': 'test_container',
        'type': 'timeline',
        'storage': {
            'type': 'local',
            'location': str(data_dir),
            'backend-id': 'test',
            'owner': '0xaaa',
            'is-local-owner': True,
        },
        'backend-id': 'test2'
    }


def test_timeline_fuse_empty(env, storage):
    env.mount_storage(['/proxy'], storage)
    assert os.listdir(env.mnt_dir / 'proxy') == []


def test_timeline_fuse_files(env, storage, data_dir):
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    (data_dir / 'dir2/dir3').mkdir(parents=True)
    (data_dir / 'dir2/dir3/file2').write_text('file 2')
    os.utime(data_dir / 'dir2/dir3/file2',
             (int(datetime(2008, 2, 3, 10, 30).timestamp()),
              int(datetime(2008, 2, 3, 10, 30).timestamp())))

    # Empty directory, should be ignored
    (data_dir / 'dir4').mkdir()

    env.mount_storage(['/proxy'], storage)
    assert treewalk.walk_all(env.mnt_dir / 'proxy') == [
        '2008/',
        '2008/02/',
        '2008/02/03/',
        '2008/02/03/dir2/',
        '2008/02/03/dir2/dir3/',
        '2008/02/03/dir2/dir3/file2/',
        '2008/02/03/dir2/dir3/file2/file2',
        '2010/',
        '2010/05/',
        '2010/05/07/',
        '2010/05/07/dir1/',
        '2010/05/07/dir1/file1/',
        '2010/05/07/dir1/file1/file1'
    ]

    assert Path(env.mnt_dir / 'proxy/2010/05/07/dir1/file1/file1').read_text() == \
        'file 1'
    assert Path(env.mnt_dir / 'proxy/2008/02/03/dir2/dir3/file2/file2').read_text() == \
        'file 2'

@pytest.fixture
def container(cli, base_dir, data_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    # this needs to be saved, so client.get_all() will see it
    with (base_dir / 'containers/macro.container.yaml').open('w') as f:
        f.write(yaml_parser.dump({
            'object': 'container',
            'owner': '0xaaa',
            'version': Manifest.CURRENT_VERSION,
            'paths': [
                '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                '/PATH',
            ],
            'backends': {
                'storage': [{
                    'timeline-root': '/timeline',
                    'object': 'storage',
                    'type': 'timeline',
                    'owner': '0xaaa',
                    'container-path': '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                    'backend-id': str(uuid.uuid4()),
                    'version': Manifest.CURRENT_VERSION,
                    'reference-container': {
                        'object': 'container',
                        'version': Manifest.CURRENT_VERSION,
                        'owner': '0xaaa',
                        'paths': ['/.uuid/39f437f3-b071-439c-806b-6d14fa55e827'],
                        'backends': {
                            'storage': [{
                                'object': 'storage',
                                'owner': '0xaaa',
                                'container-path': '/.uuid/39f437f3-b071-439c-806b-6d14fa55e827',
                                'type': 'local',
                                'location': str(data_dir),
                                'backend-id': str(uuid.uuid4()),
                                'version': Manifest.CURRENT_VERSION
                            }]
                        }
                    }
                }]
            }
        }))
    cli('container', 'sign', '-i', 'macro')

    yield 'macro'

def test_timeline_subcontainers(base_dir, container, data_dir):
    # pylint: disable=protected-access
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    (data_dir / 'dir2/dir3').mkdir(parents=True)
    (data_dir / 'dir2/dir3/file2').write_text('file 2')
    os.utime(data_dir / 'dir2/dir3/file2',
             (int(datetime(2008, 2, 3, 10, 30).timestamp()),
              int(datetime(2008, 2, 3, 10, 30).timestamp())))

    client = Client(base_dir)

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, container)
    subcontainers = list(client.all_subcontainers(container))
    assert len(subcontainers) == 2
    assert subcontainers[0].paths[1:] == [PurePosixPath('/timeline/2008/02/03')]
    assert subcontainers[0]._storage_cache[0].storage == {
        'object': 'storage',
        'type': 'delegate',
        'subdirectory': '/2008/02/03/dir2/dir3/file2',
        'owner': container.owner,
        'container-path': str(subcontainers[0].paths[0]),
        'reference-container': f'wildland:@default:{container.paths[0]}:',
        'backend-id': str(subcontainers[0].paths[0])[7:],
        'version': Manifest.CURRENT_VERSION
    }
    assert subcontainers[1].paths[1:] == [PurePosixPath('/timeline/2010/05/07')]
    assert subcontainers[1]._storage_cache[0].storage['subdirectory'] == '/2010/05/07/dir1/file1'

def test_timeline_subcontainers_fuse(base_dir, env, container, data_dir):
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    (data_dir / 'dir2/dir3').mkdir(parents=True)
    (data_dir / 'dir2/dir3/file2').write_text('file 2')
    os.utime(data_dir / 'dir2/dir3/file2',
             (int(datetime(2008, 2, 3, 10, 30).timestamp()),
              int(datetime(2008, 2, 3, 10, 30).timestamp())))

    client = Client(base_dir)

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, container)
    for subcontainer in client.all_subcontainers(container):
        env.mount_storage(subcontainer.paths[1:], client.select_storage(subcontainer).params)

    assert treewalk.walk_all(env.mnt_dir) == [
        'timeline/',
        'timeline/2008/',
        'timeline/2008/02/',
        'timeline/2008/02/03/',
        'timeline/2008/02/03/file2',
        'timeline/2010/',
        'timeline/2010/05/',
        'timeline/2010/05/07/',
        'timeline/2010/05/07/file1',
    ]

@pytest.fixture
def old_container(cli, base_dir, data_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    # this needs to be saved, so client.get_all() will see it
    with (base_dir / 'containers/macro.container.yaml').open('w') as f:
        f.write(yaml_parser.dump({
            'object': 'container',
            'owner': '0xaaa',
            'version': Manifest.CURRENT_VERSION,
            'paths': [
                '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                '/PATH',
            ],
            'backends': {
                'storage': [{
                    'object': 'storage',
                    'type': 'timeline',
                    'owner': '0xaaa',
                    'container-path': '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                    'backend-id': str(uuid.uuid4()),
                    'version': Manifest.CURRENT_VERSION,
                    'reference-container': {
                        'object': 'container',
                        'version': Manifest.CURRENT_VERSION,
                        'owner': '0xaaa',
                        'paths': ['/.uuid/39f437f3-b071-439c-806b-6d14fa55e827'],
                        'backends': {
                            'storage': [{
                                'object': 'storage',
                                'owner': '0xaaa',
                                'container-path': '/.uuid/39f437f3-b071-439c-806b-6d14fa55e827',
                                'type': 'local',
                                'location': str(data_dir),
                                'backend-id': str(uuid.uuid4()),
                                'version': Manifest.CURRENT_VERSION
                            }]
                        }
                    }
                }]
            }
        }))
    cli('container', 'sign', '-i', 'macro')

    yield 'macro'

def test_backwards_compatibility(cli, old_container, data_dir, base_dir):
    """
    Tests the backwards compatibility of the backend, based on an
    'old container' (one without the 'timeline-root' field in it's schema).
    Ensures the containers created prior to the timeline modifications
    will still be mounted correctly.
    """
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    (data_dir / 'dir2/dir3').mkdir(parents=True)
    (data_dir / 'dir2/dir3/file2').write_text('file 2')
    os.utime(data_dir / 'dir2/dir3/file2',
             (int(datetime(2008, 2, 3, 10, 30).timestamp()),
              int(datetime(2008, 2, 3, 10, 30).timestamp())))

    cli('start')
    cli('container', 'mount', old_container)

    mnt_dir = base_dir / 'wildland'

    assert treewalk.walk_all(mnt_dir / 'timeline') == [
        '2008/',
        '2008/02/',
        '2008/02/03/',
        '2008/02/03/.manifest.wildland.yaml',
        '2008/02/03/file2',
        '2010/',
        '2010/05/',
        '2010/05/07/',
        '2010/05/07/.manifest.wildland.yaml',
        '2010/05/07/file1',
    ]
