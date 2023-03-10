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
# pylint: disable=too-many-lines
"""
Monitor container manifests for changes and remount if necessary
"""

import os
from pathlib import PurePosixPath, Path
from typing import List, Optional, Tuple, Iterable, Dict, Set

from wildland.client import Client
from wildland.container import Container
from wildland.exc import WildlandError
from wildland.fs_client import WildlandFSClient, WatchEvent, PatternWatchEvent, \
    SubcontainerWatchEvent
from wildland.storage import Storage
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.watch import FileEventType
from wildland.wildland_object.wildland_object import WildlandObject
from wildland.search import Search
from wildland.wlpath import WildlandPath
from wildland.log import get_logger

logger = get_logger('remounter')


class Remounter:
    """
    A class for watching files and remounting if necessary.

    This works by registering watches in WL (FUSE) daemon for requested files.
    Watching files outside of WL tree is not supported (there is no direct file
    change notification - like inotify - support).
    When file change is reported, the container in question is loaded and then
    compared with mounted state (same as the ``wl container mount`` does - either
    mount it new, or remount relevant storages).

    When a Wildland Path watching is requested, it is resolved to a list of
    manifests in relevant container manifests-catalog, using
    :py:meth:`Search.get_watch_params`. If some of those containers are not mounted,
    the function returns also a list of containers to mount. Those containers are mounted
    only at "backend unique" paths (in /.users/... hierarchy) to not pollute user view.
    Then, they are monitored similarly to normal files like described above, with the difference
    that a file change event results in a Wildland path resolve again, instead of loading
    just changed file. This way, it will detect any new/removed containers if the change was to
    a container in manifests catalog like `manifest-pattern` field, or redirecting to a
    different storage.

    Currently, this class does not unmount containers from manifests catalog that are no longer
    needed (neither because of some manifest catalog change, nor because of simply
    terminating remounter).
    """

    def __init__(self, client: Client, fs_client: WildlandFSClient, container_names: List[str],
                 with_subcontainers=True, additional_patterns: Optional[List[str]] = None):
        self.client = client
        self.fs_client = fs_client

        # Queued operations
        self.to_mount: List[Tuple[Container,
                                  Iterable[Storage],
                                  Iterable[Iterable[PurePosixPath]],
                                  Optional[Container]]] = []
        self.to_unmount: List[int] = []

        # manifest path -> main container path
        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

        self.patterns: List[str] = []
        self.wlpaths: List[WildlandPath] = []
        # patterns to watch WL paths
        self.wlpath_patterns: Dict[str, List[WildlandPath]] = {}
        # Containers watched for subcontainers
        self.outside_containers: List[Container] = []
        self.inside_containers: List[Container] = []

        if additional_patterns:
            self.patterns.extend(additional_patterns)
        for name in container_names:

            if WildlandPath.match(name):
                self.wlpaths.append(WildlandPath.from_str(name))
                continue

            path = Path(os.path.expanduser(name)).resolve()
            if path.is_relative_to(self.fs_client.mount_dir):
                relpath = path.relative_to(self.fs_client.mount_dir)
                self.patterns.append(str(PurePosixPath('/') / relpath))
                continue

            assert self.client.find_local_manifest(WildlandObject.Type.CONTAINER, name)
            self.outside_containers.extend(self.client.load_containers_from(name))

        self.with_subcontainers = with_subcontainers

        # wlpath -> resolved containers (stored as its main path)
        self.wlpath_main_paths: Dict[WildlandPath, Set[PurePosixPath]] = {}

    def run(self):
        """
        Run the main loop.
        """

        self.init_watch_params()
        while True:
            patterns = self.patterns + list(self.wlpath_patterns.keys())
            containers = self.outside_containers + self.inside_containers
            if patterns:
                logger.info('Using patterns: %r', patterns)
            if containers:
                logger.info('Watching containers: %s', '\n'.join((c.uuid for c in containers)))

            for events in self.fs_client.watch(
                    patterns=patterns,
                    wl_client=self.client,
                    containers=containers,
                    with_initial=True
            ):
                any_wlpath_changed, container_changed = self.handle_events(events)

                self.unmount_pending()
                self.mount_pending()

                any_pattern_changed = False
                if any_wlpath_changed:
                    # recalculate wlpath patterns and refresh outside containers
                    any_pattern_changed = self.init_watch_params()

                if any_pattern_changed or container_changed:
                    logger.info('Re-registering watches.')
                    break

    def init_watch_params(self) -> bool:
        """
        Resolve requested WL paths and collect containers + patterns to be watched.
        This will also mount required containers if necessary.

        :return True if patterns have changed
        """

        if self.with_subcontainers:
            # (re)mounting containers from "outside" the wildland file system
            for container in self.outside_containers:
                self.handle_changed_container(container)
            self.mount_pending()

        patterns: Dict[str, List[WildlandPath]] = {}
        for wlpath in self.wlpaths:
            search = Search(self.client, wlpath,
                            aliases=self.client.config.aliases,
                            fs_client=self.fs_client)
            mount_cmds, patterns_for_path = search.get_watch_params()
            try:
                if mount_cmds:
                    self.fs_client.mount_multiple_containers(
                        mount_cmds, remount=False, unique_path_only=True)
            except WildlandError as e:
                logger.error('failed to mount container(s) to watch WL path %s: %s', wlpath, str(e))
                # keep the old patterns
                for wlpattern in self.wlpath_patterns:
                    if wlpath in self.wlpath_patterns[wlpattern]:
                        patterns.setdefault(wlpattern, []).append(wlpath)
            else:
                for pattern in patterns_for_path:
                    patterns.setdefault(str(pattern), []).append(wlpath)

        patterns_changed = set(patterns.keys()) != set(self.wlpath_patterns.keys())
        self.wlpath_patterns = patterns
        return patterns_changed

    def handle_events(self, events) -> Tuple[bool, bool]:
        """
        Handle a single batch of watch event.
        Returns whether there may be a need to recalculate watch patterns
        """
        any_wlpath_changed = False
        container_with_children_changed = False
        # avoid processing the same wlpath multiple times - each time we re-evaluate
        # all the containers resolved from them, regardless which manifest the event was about
        wlpaths_processed = set()
        for event in events:
            try:
                if isinstance(event, PatternWatchEvent) and event.pattern in self.wlpath_patterns:
                    any_wlpath_changed = True
                    for wlpath in self.wlpath_patterns[event.pattern]:
                        if wlpath not in wlpaths_processed:
                            self.handle_wlpath_event(event, wlpath)
                            wlpaths_processed.add(wlpath)
                else:
                    container_with_children_changed = self.handle_event(event)
            except Exception as e:
                logger.exception('error in handle_event: %s', str(e))
        return any_wlpath_changed, container_with_children_changed

    def handle_wlpath_event(self, event: WatchEvent, wlpath: WildlandPath):
        """
        Handle a single file change event related to watched WL path.
        Queue mount/unmount operations in self.to_mount and self.to_unmount.
        """

        logger.info('WL path \'%s\' event %s: %s', wlpath, event.event_type, event.path)

        search = Search(self.client, wlpath,
                        aliases=self.client.config.aliases,
                        fs_client=self.fs_client)

        new_main_paths = set()
        try:
            for container in search.read_container():
                main_path = self.fs_client.get_user_container_path(
                    container.owner, container.paths[0])
                self.handle_changed_container(container)
                new_main_paths.add(main_path)

            for main_path in self.wlpath_main_paths.get(wlpath, set()).difference(new_main_paths):
                storage_id, pseudo_storage_id = self.fs_client.find_storage_id_by_path(main_path)
                if storage_id is not None:
                    assert pseudo_storage_id is not None
                    logger.info('  (unmount %d)', storage_id)
                    self.to_unmount += [storage_id, pseudo_storage_id]
                else:
                    logger.info('  (not mounted)')
        except Exception:
            # in case of search error, do not forget about any earlier container,
            # but also add newly mounted ones
            self.wlpath_main_paths.setdefault(wlpath, set()).update(new_main_paths)
            raise
        else:
            self.wlpath_main_paths[wlpath] = new_main_paths

    def handle_event(self, event: WatchEvent):
        """
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        """

        logger.info('Event %s: %s', event.event_type, event.path)

        # Handle delete: unmount if the file was mounted.

        if event.event_type == FileEventType.DELETE:
            # Find out if we've already seen the file, and can match it to an mounted storage.
            storage_id: Optional[int] = None
            pseudo_storage_id: Optional[int] = None

            if event.path in self.main_paths:
                storage_id, pseudo_storage_id = self.fs_client.find_storage_id_by_path(
                    self.main_paths[event.path])

                if storage_id is not None:
                    assert pseudo_storage_id is not None
                    logger.info('  (unmount %d)', storage_id)
                    self.to_unmount += [storage_id, pseudo_storage_id]
                else:
                    logger.info('  (not mounted)')

                # Stop tracking the file
                if event.path in self.main_paths:
                    del self.main_paths[event.path]

        # Handle create/modify:

        container_with_children_changed = False

        if event.event_type in [FileEventType.CREATE, FileEventType.MODIFY]:
            if isinstance(event, SubcontainerWatchEvent):
                container = self.load_subcontainer(event)
            else:
                container = self.load_container(event)
                # The container manifest changed, update `containers_storages` if necessary
                if self.with_subcontainers:
                    storage = self.client.select_storage(container)
                    if container in self.inside_containers:
                        self.inside_containers.append(container)
                        container_with_children_changed = True
                    elif container not in self.inside_containers:
                        params = storage.params
                        sb = StorageBackend.from_params(params, deduplicate=True)
                        with sb:
                            if sb.can_have_children:
                                self.inside_containers.append(container)
                                container_with_children_changed = True

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_container_path(
                container.owner, container.paths[0])
            self.handle_changed_container(container)

        return container_with_children_changed

    def load_container(self, event):
        """
        Loads container from file.
        """
        local_path = self.fs_client.mount_dir / event.path.relative_to('/')
        container = self.client.load_object_from_file_path(
            WildlandObject.Type.CONTAINER, local_path)
        return container

    def load_subcontainer(self, event):
        """
        Loads subcontainers.
        """
        assert event.subcontainer is not None
        container = self.client.load_subcontainer_object(
            event.container, event.storage, event.subcontainer)
        assert isinstance(container, Container)
        return container

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

            for path in self.fs_client.get_orphaned_container_storage_paths(container, storages):
                storage_id, pseudo_storage_id = self.fs_client.find_storage_id_by_path(path)
                assert storage_id is not None
                assert pseudo_storage_id is not None
                logger.info('  (removing orphan storage %s @ id: %d)', path, storage_id)
                self.to_unmount += [storage_id, pseudo_storage_id]

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
