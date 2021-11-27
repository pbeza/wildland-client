# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
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
"""
SubcontainerRemounter class responsible for mount-watching children of
a chosen container
"""
from pathlib import PurePosixPath
from typing import List, Tuple, Iterable, Optional, Dict

from wildland.client import Client
from wildland.container import Container
from wildland.fs_client import WildlandFSClient, WatchSubcontainerEvent
from wildland.log import get_logger
from wildland.storage import Storage
from wildland.storage_backends.watch import FileEventType
from .exc import WildlandError

logger = get_logger('subcontainer_remounter')


class SubcontainerRemounter:
    """
    Remounter used to keep track of changes in the children containers
    of a chosen Wildland container.
    The remounter is meant to automatically mount/unmount/remount containers
    as changes appear in the filesystem.
    """

    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 containers_storage: Dict[Container, Storage]):
        self.containers_storage = containers_storage
        self.client = client
        self.fs_client = fs_client

        self.to_mount: List[Tuple[Container,
                            Iterable[Storage],
                            Iterable[Iterable[PurePosixPath]],
                            Optional[Container]]] = []
        self.to_unmount: List[int] = []

        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

    def run(self):
        """
        Run the main loop.
        """

        while True:
            for events in self.fs_client.watch_subcontainers(
                    self.client, self.containers_storage, with_initial=True):
                for event in events:
                    self.handle_subcontainer_event(event)
                self.unmount_pending()
                self.mount_pending()

    def handle_subcontainer_event(self, event: WatchSubcontainerEvent):
        """
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        """
        logger.info('Event %s: %s', event.event_type, event.path)

        if event.event_type == FileEventType.DELETE:
            # Find out if we've already seen the file, and can match it to a mounted storage.
            storage_id: Optional[int] = None
            if event.path in self.main_paths:
                storage_id = self.fs_client.find_storage_id_by_path(self.main_paths[event.path])

            # Stop tracking the file
            if event.path in self.main_paths:
                del self.main_paths[event.path]

            if storage_id is not None:
                logger.info('  (unmount %d)', storage_id)
                self.to_unmount.append(storage_id)
            else:
                logger.info('  (not mounted)')

        if event.event_type in [FileEventType.CREATE, FileEventType.MODIFY]:
            container = self.client.load_subcontainer_object(
                event.container, event.storage, event.subcontainer)

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_container_path(
                container.owner, container.paths[0])

            self.handle_changed_container(container)

    def handle_changed_container(self, container: Container):
        """
        Queue mount/remount of a container. This considers both new containers and
        already mounted containers, including changes in storages

        :param container: container to (re)mount
        :return:
        """
        user_paths = self.client.get_bridge_paths_for_user(container.owner)
        storages = self.client.get_storages_to_mount(container)
        if self.fs_client.find_primary_storage_id(container) is None:
            logger.info('  new: %s', str(container))
            self.to_mount.append((container, storages, user_paths, None))
        else:
            storages_to_remount = []

            for path in self.fs_client.get_orphaned_container_storage_paths(
                    container, storages):
                storage_id = self.fs_client.find_storage_id_by_path(path)
                assert storage_id is not None
                logger.info('  (removing orphan %s @ id: %d)', path, storage_id)
                self.to_unmount.append(storage_id)

            for storage in storages:
                if self.fs_client.should_remount(container, storage, user_paths):
                    logger.info('  (remounting: %s)', storage.backend_id)
                    storages_to_remount.append(storage)
                else:
                    logger.info('  (not changed: %s)', storage.backend_id)

            if storages_to_remount:
                self.to_mount.append((container, storages_to_remount, user_paths, None))

    def unmount_pending(self):
        """
        Unmount queued containers.
        """

        for storage_id in self.to_unmount:
            try:
                self.fs_client.unmount_storage(storage_id)
            except WildlandError as e:
                logger.error('failed to unmount storage %d: %s', storage_id, e)
        self.to_unmount.clear()

    def mount_pending(self):
        """
        Mount queued containers.
        """

        try:
            self.fs_client.mount_multiple_containers(self.to_mount, remount=True)
        except WildlandError as e:
            logger.error('failed to mount some storages: %s', e)
        self.to_mount.clear()
