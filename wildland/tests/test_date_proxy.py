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
from pathlib import Path, PurePosixPath
import os
from datetime import datetime
import yaml

import pytest

from .fuse_env import FuseEnv
from ..client import Client


def test_date_proxy_with_url(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--path', '/tmp/local-path',
        '--container', 'referenceContainer')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    reference_url = f'file://{reference_path}'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'date-proxy', 'ProxyStorage',
        '--reference-container-url', reference_url,
        '--container', 'Container')

    client = Client(base_dir)
    client.recognize_users()

    # When loaded directly, the storage manifest contains container URL...
    storage = client.load_storage_from('ProxyStorage')
    assert storage.params['reference-container'] == reference_url

    # But select_storage loads also the reference manifest
    container = client.load_container_from('Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'date-proxy'
    reference_storage = storage.params['storage']
    assert isinstance(reference_storage, dict)
    assert reference_storage['type'] == 'local'


@pytest.fixture
def env():
    env = FuseEnv()
    try:
        env.mount()
        yield env
    finally:
        env.destroy()


@pytest.fixture
def data_dir(base_dir):
    data_dir = Path(base_dir / 'data')
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def storage(data_dir):
    return {
        'type': 'date-proxy',
        'storage': {
            'type': 'local',
            'path': str(data_dir),
        }
    }


def walk_all(path: Path):
    return list(_walk_all(path, path))

def _walk_all(root, path):
    for sub_path in sorted(path.iterdir()):
        if sub_path.is_dir():
            yield str(sub_path.relative_to(root)) + '/'
            yield from _walk_all(root, sub_path)
        else:
            yield str(sub_path.relative_to(root))


def test_date_proxy_fuse_empty(env, storage):
    env.mount_storage(['/proxy'], storage)
    assert os.listdir(env.mnt_dir / 'proxy') == []


def test_date_proxy_fuse_files(env, storage, data_dir):
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
    assert walk_all(env.mnt_dir / 'proxy') == [
        '2008/',
        '2008/02/',
        '2008/02/03/',
        '2008/02/03/dir2/',
        '2008/02/03/dir2/dir3/',
        '2008/02/03/dir2/dir3/file2',
        '2010/',
        '2010/05/',
        '2010/05/07/',
        '2010/05/07/dir1/',
        '2010/05/07/dir1/file1',
    ]

    assert Path(env.mnt_dir / 'proxy/2010/05/07/dir1/file1').read_text() == \
        'file 1'
    assert Path(env.mnt_dir / 'proxy/2008/02/03/dir2/dir3/file2').read_text() == \
        'file 2'

@pytest.fixture
def container(cli, base_dir, data_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    # this needs to be saved, so client.load_containers() will see it
    (base_dir / 'containers').mkdir(parents=True)
    with (base_dir / 'containers/macro.container.yaml').open('w') as f:
        f.write(yaml.dump({
            'object': 'container',
            'owner': '0xaaa',
            'paths': [
                '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                '/PATH',
            ],
            'backends': {
                'storage': [{
                    'type': 'date-proxy',
                    'owner': '0xaaa',
                    'container-path': '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                    'reference-container': {
                        'object': 'container',
                        'owner': '0xaaa',
                        'paths': ['/.uuid/39f437f3-b071-439c-806b-6d14fa55e827'],
                        'backends': {
                            'storage': [{
                                'owner': '0xaaa',
                                'container-path': '/.uuid/39f437f3-b071-439c-806b-6d14fa55e827',
                                'type': 'local',
                                'path': str(data_dir),
                            }]
                        }
                    }
                }]
            }
        }))
    cli('container', 'sign', '-i', 'macro')

    yield 'macro'

def test_date_proxy_subcontainers(base_dir, container, data_dir):
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
    client.recognize_users()

    container = client.load_container_from(container)
    subcontainers = list(client.all_subcontainers(container))
    assert len(subcontainers) == 2
    assert subcontainers[0].paths[1:] == [PurePosixPath('/timeline/2008/02/03')]
    assert subcontainers[0].backends[0] == {
        'type': 'delegate',
        'subdirectory': '/2008/02/03',
        'owner': container.owner,
        'container-path': str(subcontainers[0].paths[0]),
        'reference-container': f'wildland:@default:{container.paths[0]}:'
    }
    assert subcontainers[1].paths[1:] == [PurePosixPath('/timeline/2010/05/07')]
    assert subcontainers[1].backends[0]['subdirectory'] == '/2010/05/07'

def test_date_proxy_subcontainers_fuse(base_dir, env, container, data_dir):
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
    client.recognize_users()

    container = client.load_container_from(container)
    for subcontainer in client.all_subcontainers(container):
        env.mount_storage(subcontainer.paths[1:], client.select_storage(subcontainer).params)

    assert walk_all(env.mnt_dir) == [
        'timeline/',
        'timeline/2008/',
        'timeline/2008/02/',
        'timeline/2008/02/03/',
        'timeline/2008/02/03/dir2/',
        'timeline/2008/02/03/dir2/dir3/',
        'timeline/2008/02/03/dir2/dir3/file2',
        'timeline/2010/',
        'timeline/2010/05/',
        'timeline/2010/05/07/',
        'timeline/2010/05/07/dir1/',
        'timeline/2010/05/07/dir1/file1',
    ]
