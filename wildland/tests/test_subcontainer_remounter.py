# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                   Piotr Bartman <prbartman@invisiblethingslab.com>
#                   Maja Kostacinska <maja@wildland.io>
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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Tuple, Callable, Dict

import pytest

from ..client import Client
from ..container import Container
from ..storage import Storage
from ..storage_backends.base import StorageBackend
from ..subcontainer_remounter import SubcontainerRemounter
from ..wildland_object.wildland_object import WildlandObject


def get_container_uuid_from_uuid_path(uuid_path: str):
    match = re.search('/.uuid/(.+?)$', uuid_path)
    return match.group(1) if match else ''


@pytest.fixture
def setup(base_dir, cli, control_client):
    control_client.expect('status', {})
    os.mkdir(base_dir / 'reference-storage')
    with open(base_dir/ 'reference-storage/file1.txt', 'w'):
        pass
    with open(base_dir/ 'reference-storage/file2.txt', 'w'):
        pass

    cli('user', 'create', 'User', '--key', '0xaaa')

    cli('container', 'create', 'reference-container', '--path', '/reference',
        '--path', '/.uuid/0000000000-1111-0000-0000-000000000000',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'reference-storage',
        '--location', base_dir / 'reference-storage',
        '--container', 'reference-container',
        '--trusted')

    cli('container', 'create', 'timeline-container', '--path', '/timeline',
        '--path', '/.uuid/0000000000-1111-0000-1111-000000000000',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'timeline', 'timeline-storage',
        '--container', 'timeline-container',
        '--reference-container-url', 'wildland::/.uuid/0000000000-1111-0000-0000-000000000000:',
        '--timeline-root', '/root', '--no-encrypt-manifest',
        '--watcher-interval', '10')

@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client


class TerminateSubcontainerRemounter(Exception):
    pass


@dataclass
class ExpectedMount:
    owner: str

    paths: List[PurePosixPath]
    #: backend-id -> storage-id
    backends: Dict[str, int]


class SubcontainerRemounterWrapper(SubcontainerRemounter):
    def __init__(self, *args, control_client, **kwargs):
        super().__init__(*args, **kwargs)
        # list of:
        # - storages to mount as ExpectedMount objects
        #   storage-ids are used to mock given storage as mounted
        # - storages to unmount
        # - callable to apply modifications after processing request
        self.expected_actions: List[Tuple[List[ExpectedMount], List[int], Callable]] = []
        self.call_counter = 0
        self.control_client = control_client

    def expect_action(self, to_mount, to_unmount, callback):
        """
        Register expected action to be called by Remounter.
        Actions are expected in order of expect_action() calls.
        """
        self.expected_actions.append((to_mount, to_unmount, callback))

    def mount_pending(self):
        """
        Mock override real mount_pending() to check if queued operations match expectations
        registered with expect_action() calls.
        """
        assert self.call_counter < len(self.expected_actions), \
            f'expected only {len(self.expected_actions)} remounter iterations'
        to_mount, to_unmount, callback = self.expected_actions[self.call_counter]
        self.call_counter += 1

        assert len(self.to_mount) == len(to_mount), f'expected {to_mount}, actual {self.to_mount}'
        # TODO: sort
        for expected, actual in zip(to_mount, self.to_mount):
            # container
            assert expected.owner == actual[0].owner
            assert expected.paths == actual[0].paths
            # backends
            assert len(expected.backends) == len(actual[1])
            storage_id = None
            for expected_b, actual_b in zip(
                    sorted(expected.backends.items()),
                    sorted(actual[1], key=lambda s: s.backend_id)):
                assert expected_b[0] == actual_b.backend_id
                if actual_b.is_primary:
                    storage_id = expected_b[1]
                # register as mounted - backend specific path
                uuid = get_container_uuid_from_uuid_path(str(expected.paths[0]))
                self.control_client.add_storage_paths(
                    expected_b[1],
                    [f'/.users/{expected.owner}:/.backends/{uuid}/{expected_b[0]}']
                )

                # calculate storage tag, so params/paths change will be detected
                mount_paths = self.fs_client.get_storage_mount_paths(actual[0], actual_b, actual[2])
                tag = self.fs_client.get_storage_tag(mount_paths, actual_b.params)
                self.control_client.results['info'][expected_b[1]]['extra']['tag'] = tag

            # if there is primary storage, mount under generic paths too
            if storage_id is not None:
                self.control_client.add_storage_paths(
                    storage_id,
                    [f'/.users/{expected.owner}:{path}' for path in expected.paths]
                )
        self.to_mount.clear()

        # check to_unmount
        assert len(self.to_unmount) == len(to_unmount), \
            f'call {self.call_counter-1}: expected {to_unmount}, actual {self.to_unmount}'
        assert set(self.to_unmount) == set(to_unmount), \
            f'call {self.call_counter-1}: expected {to_unmount}, actual {self.to_unmount}'
        for storage_id in to_unmount:
            self.control_client.del_storage(storage_id)
        self.to_unmount.clear()

        self.fs_client.clear_cache()

        if callback is not None:
            callback()

    def unmount_pending(self):
        """
        Do nothing on unmount. to_unmount() queue is already checked in mount_pending()
        """

    def check(self):
        not_executed = self.expected_actions[self.call_counter:]
        assert not not_executed, \
            "The following actions were not executed: {!r}".format(not_executed)


def test_mount_unmount_child(cli, client, control_client, base_dir):
    control_client.expect('status', {})
    control_client.expect('paths', {})
    control_client.expect('mount')
    cli('container', 'mount', 'timeline-container')

    container_name = 'timeline-container'
    containers_storage: Dict[Container, Storage] = {
        container: client.select_storage(container)
        for container in client.load_containers_from(container_name)
    }

    timeline_container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'timeline-container')
    timeline_storage = client.select_storage(timeline_container)
    timeline_backend = StorageBackend.from_params(timeline_storage.params, deduplicate=True)
    #change to paths_only=true
    children = list(timeline_backend.get_children(client))

    file2_path = ''
    for child in children:
        if 'file2.txt' in str(child[0]):
            file2_path = child[0]

    remounter = SubcontainerRemounterWrapper(client, client.fs_client, containers_storage,
                                             control_client=control_client)
    control_client.expect('add-subcontainer-watch', 1)
    control_client.queue_event([])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'DELETE', 'path': str(file2_path)}])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'CREATE', 'path': str(file2_path)}])
    control_client.queue_event(TerminateSubcontainerRemounter())

    def remove_file():
        os.remove(base_dir/ 'reference-storage/file2.txt')

    def add_file():
        with open(base_dir/ 'reference-storage/file2.txt', 'w'):
            pass

    remounter.expect_action([], [], remove_file)
    remounter.expect_action([],
        [1],  add_file
    )
    remounter.expect_action([ExpectedMount(
            '0xaaa',
            file2_path,
            {timeline_storage.params['backend-id']: 1}
        )], [], None)
    with pytest.raises(TerminateSubcontainerRemounter):
        remounter.run()
    remounter.check()
