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

'''
Stuff related to publishing and unpublishing containers.
'''

import collections.abc
import logging
import pathlib
from typing import Optional, cast

from .client import Client
from .container import Container
from .exc import WildlandError
from .manifest.manifest import ManifestError
from .search import StorageDriver
from .storage import Storage

logger = logging.getLogger('publish')


class Publisher:
    # Between two publish operations, things might have changed:
    # - different container paths,
    # - different set of storages.
    # Things that (we assume) didn't change:
    # - container uuid,
    # - manifest-pattern,
    # - base-url.

    """
    A behavior for publishing and unpublishing manifests

    >>> Publisher(client, container1).publish_manifest()
    >>> Publisher(client, container2).unpublish_manifest()
    """
    def __init__(self, client: Client, container: Container,
            infrastructure: Optional[Container] = None):
        self.client = client
        self.container = container

        if infrastructure is not None:
            raise NotImplementedError(
                'choosing infrastructure is not supported')

        self.infra_storage = next(self._get_storages_for_publish())
        assert self.infra_storage.manifest_pattern['type'] == 'glob'
        self.pattern = self.infra_storage.manifest_pattern['path']
        self.container_uuid_path = self.container.get_uuid_path()

    def _get_relpath_for_storage_manifest(self, storage):
        # we publish only a single manifest for a storage, under `/.uuid/` path
        return pathlib.PurePosixPath(self.pattern
            .replace('*', storage.params['backend-id'])
            .replace('{path}', str(self.container_uuid_path.relative_to('/')))
        ).relative_to('/')

    def _get_relpaths_for_container_manifests(self, container):
        path_pattern = self.pattern.replace('*', container.ensure_uuid())

        # always return /.uuid/ path first
        yield pathlib.PurePosixPath(path_pattern
            .replace('{path}', str(self.container_uuid_path.relative_to('/')))
        ).relative_to('/')

        if '{path}' in path_pattern:
            for path in container.expanded_paths:
                if path == self.container_uuid_path:
                    continue
                yield pathlib.PurePosixPath(path_pattern.replace(
                    '{path}', str(path.relative_to('/')))).relative_to('/')


    def publish_container(self) -> None:
        """
        Publish the manifest
        """
        return self._publish_container(False)

    def unpublish_container(self) -> None:
        """
        Unpublish the manifest
        """
        return self._publish_container(True)

    def _publish_container(self, just_unpublish: bool) -> None:
        """
        Publish a container to a container owner by the same user.
        """
        # Marczykowski-Górecki's Algorithm:
        # 1) choose infrastructure container from container owner
        #    - if the container was published earlier, the same infrastructure
        #      should be chosen; this will make sense when user will be able to
        #      choose to which infrastructure the container should be published
        # 2) generate all new relpaths for the container and storages
        # 3) try to fetch container from new relpaths; check if the file
        #    contains the same container; if yes, generate relpaths for old
        #    paths
        # 4) remove old copies of manifest for container and storages (only
        #    those that won't be overwritten later)
        # 5) post new storage manifests
        # 6) post new container manifests starting with /.uuid/ one
        #
        # For unpublishing, instead of 4), 5) and 6), all manifests are removed
        # from relpaths and no new manifests are published.

        container_relpaths = list(
            self._get_relpaths_for_container_manifests(self.container))
        storage_relpaths = {}
        old_relpaths_to_remove = set()

        with StorageDriver.from_storage(self.infra_storage) as driver:
            for i in range(len(self.container.backends)):
                if isinstance(self.container.backends[i],
                        collections.abc.Mapping):
                    continue
                backend = self.client.load_storage_from_url(
                    cast(str, self.container.backends[i]), self.container.owner)
                relpath = self._get_relpath_for_storage_manifest(backend)
                assert relpath not in storage_relpaths
                storage_relpaths[relpath] = backend
                self.container.backends[i] = (
                    driver.storage_backend.get_url_for_path(relpath))

            # fetch from /.uuid path
            try:
                old_container_manifest_data = driver.read_file(
                    container_relpaths[0])
            except FileNotFoundError:
                pass
            else:
                old_container = self.client.session.load_container(
                    old_container_manifest_data)

                if not old_container.ensure_uuid() == self.container.ensure_uuid():
                    # we just downloaded this file from container_relpaths[0], so
                    # things are very wrong here
                    raise WildlandError(
                        f'old version of container manifest at storage '
                        f'{driver.storage.params["backend-id"]} has serious '
                        f'problems; please remove it manually')

                old_relpaths_to_remove.update(set(
                    self._get_relpaths_for_container_manifests(old_container)))
                for url_or_dict in old_container.backends:
                    if isinstance(url_or_dict, collections.abc.Mapping):
                        continue
                    old_relpaths_to_remove.add(
                        driver.storage_backend.get_path_for_url(url_or_dict))

            if just_unpublish:
                old_relpaths_to_remove.update(container_relpaths)
                old_relpaths_to_remove.update(storage_relpaths)
            else:
                old_relpaths_to_remove.difference_update(container_relpaths)
                old_relpaths_to_remove.difference_update(storage_relpaths)

            # remove
            for relpath in old_relpaths_to_remove:
                try:
                    driver.remove_file(relpath)
                except FileNotFoundError:
                    pass

            if not just_unpublish:
                for relpath, storage in storage_relpaths.items():
                    driver.makedirs(relpath.parent)
                    driver.write_file(relpath,
                        self.client.session.dump_storage(storage))

                for relpath in container_relpaths:
                    driver.makedirs(relpath.parent)
                    driver.write_file(relpath,
                        self.client.session.dump_container(self.container))

    def _get_storages_for_publish(self) -> Storage:
        '''
        Iterate over all suitable storages to publish container manifest.
        '''
        owner = self.client.load_user_by_name(self.container.owner)

        ok = False
        rejected = []
        if not owner.containers:
            rejected.append(f'user {owner} has no infrastructure containers')

        for c in owner.containers:
            try:
                container_candidate = (
                    self.client.load_container_from_url_or_dict(
                        c, self.container.owner))

                all_storages = list(
                    self.client.all_storages(container=container_candidate))

                if not all_storages:
                    rejected.append(
                        f'container {container_candidate.ensure_uuid()} '
                        'has no available storages')
                    continue

                for storage_candidate in all_storages:
                    if storage_candidate.manifest_pattern is None:
                        rejected.append(
                            f'storage {storage_candidate.params["backend-id"]} of '
                            f'container {container_candidate.ensure_uuid()} '
                            'does not have manifest_pattern')
                        continue

                    if not storage_candidate.is_writeable:
                        rejected.append(
                            f'storage {storage_candidate.params["backend-id"]} of '
                            f'container {container_candidate.ensure_uuid()} '
                            'is not writeable')
                        continue

                    # Attempt to mount the storage driver first.
                    # Failure in attempt to mount the backend should try the next storage from the
                    # container and if still not mounted, move to the next container
                    try:
                        with StorageDriver.from_storage(storage_candidate) as _driver:
                            ok = True
                            yield storage_candidate

                            # yield at most a single storage for a container
                            break

                    except (WildlandError, PermissionError, FileNotFoundError) as ex:
                        rejected.append(
                            f'storage {storage_candidate.params["backend-id"]} of '
                            f'container {container_candidate.ensure_uuid()} '
                            f'could not be mounted: {ex!s}')
                        logger.debug(
                            'Failed to mount storage when publishing with '
                            'exception: %s',
                            ex)
                        continue

            except (ManifestError, WildlandError) as ex:
                rejected.append(
                    f'container {container_candidate.ensure_uuid()} has '
                    'serious problems: {ex!s}')
                logger.debug(
                    'Failed to load container when publishing with '
                    'exception: %s',
                    ex)
                continue

        if not ok:
            raise WildlandError(
                'Cannot find any container suitable as publishing platform:'
                + ''.join(f'\n- {i}' for i in rejected))
