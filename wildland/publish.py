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
Stuff related to publishing and unpublishing manifests.
'''

import collections.abc
import logging
from pathlib import PurePosixPath
from typing import Optional, Generator, cast

from .client import Client
from .container import Container
from .user import User
from .bridge import Bridge
from .exc import WildlandError
from .manifest.manifest import ManifestError, WildlandObjectType, Publishable
from .storage_driver import StorageDriver
from .storage import Storage

logger = logging.getLogger('publish')


class Publisher:
    # Between two publish operations, things might have changed:
    # - different manifests paths,
    # - different set of storages.
    # Things that (we assume) didn't change:
    # - manifests uid (most likely a uuid),
    # - manifest-pattern,
    # - base-url.

    """
    A behavior for publishing and unpublishing manifests

    >>> Publisher(client, manifest1).publish_manifest()
    >>> Publisher(client, manifest2).unpublish_manifest()
    """

    def __init__(self, client: Client, manifest: Publishable,
                 infrastructure: Optional[Container] = None):
        assert issubclass(type(manifest), Publishable)

        self.client = client
        self.manifest = manifest

        if infrastructure is not None:
            raise NotImplementedError(
                'choosing infrastructure is not supported')

    def publish_manifest(self) -> None:
        """
        Publish the manifest
        """
        _StoragePublisher(self, next(self._get_storages_for_publish())).publish_manifest(False)

    def unpublish_manifest(self) -> None:
        """
        Unpublish the manifest
        """
        _StoragePublisher(self, next(self._get_storages_for_publish())).publish_manifest(True)

    def _get_storages_for_publish(self) -> Generator[Storage, None, None]:
        '''
        Iterate over all suitable storages to publish manifest.
        '''
        owner = self.manifest.get_publish_user_owner()
        user = self.client.load_object_from_name(WildlandObjectType.USER, owner)

        ok = False
        rejected = []
        if not user.containers:
            rejected.append(f'user {user.owner} has no infrastructure containers')

        for c in user.containers:
            try:
                container_candidate = (
                    self.client.load_object_from_url_or_dict(
                        WildlandObjectType.CONTAINER, c, owner))

                all_storages = list(
                    self.client.all_storages(container=container_candidate))

                if not all_storages:
                    rejected.append(
                        f'container {container_candidate.ensure_uuid()} '
                        'has no available storages')
                    continue

                for storage_candidate in all_storages:
                    if 'manifest-pattern' not in storage_candidate.params or \
                            storage_candidate.params['manifest-pattern']['type'] != 'glob':
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
                    f'container {repr(c)} has serious problems: {ex!s}')
                logger.debug(
                    'Failed to load container when publishing with exception: %s', ex)
                continue

        if not ok:
            raise WildlandError(
                'Cannot find any container suitable as publishing platform:'
                + ''.join(f'\n- {i}' for i in rejected))


class _StoragePublisher:
    """
    Helper class: publish/unpublish for a single storage

    This is because publishing is done to single storage, but unpublish should
    be attempted from all viable infra containers to avoid a situation when user
    commands an unpublish, we find no manifests at some container and report to
    user that there no manifests, which would obviously be wrong.
    """

    def __init__(self, publisher: Publisher, infra_storage: Storage):
        self.client = publisher.client
        self.manifest = publisher.manifest
        self.manifest_unique_id = publisher.manifest.get_unique_publish_id()

        # TODO this requires a more subtle manifest-pattern rewrite including more types
        # of writeable and publisheable-to storages
        self.infra_storage = infra_storage
        assert self.infra_storage.params['manifest-pattern']['type'] == 'glob'
        self.pattern = self.infra_storage.params['manifest-pattern']['path']

    def _get_relpaths_for_manifests(self, manifest: Publishable):
        manifest_primary_publish_path = manifest.get_primary_publish_path()
        manifest_extra_publish_paths = manifest.get_additional_publish_paths()

        path_pattern = self.pattern.replace('*', self.manifest_unique_id)

        # always return /.uuid/ path first
        yield PurePosixPath(
            path_pattern.replace('{path}', str(manifest_primary_publish_path.relative_to('/')))
        ).relative_to('/')

        if '{path}' in path_pattern:
            for path in manifest_extra_publish_paths:
                if path == manifest_primary_publish_path:
                    continue
                yield PurePosixPath(path_pattern.replace(
                    '{path}', str(path.relative_to('/')))).relative_to('/')

    def publish_manifest(self, just_unpublish: bool) -> None:
        """
        Publish a manifest to the manifest owner's catalog.
        """
        # Marczykowski-Górecki's Algorithm:
        # 1) choose infrastructure container from the manifest owner
        #    - if the manifest was published earlier, the same infrastructure
        #      should be chosen; this will make sense when user will be able to
        #      choose to which infrastructure the manifest should be published
        # 2) generate all new relpaths for the manifest and its storages (if applicable)
        # 3) try to fetch the manifest from new relpaths; check if the file
        #    contains the same manifest body; if yes, generate relpaths for old
        #    paths
        # 4) remove old copies of the manifest and its potential storages (only
        #    those that won't be overwritten later)
        # 5) post new storage manifests (for containers)
        # 6) post new manifest files starting with the /.uuid/ one
        #
        # For unpublishing, instead of 4), 5) and 6), all manifests are removed
        # from relpaths and no new manifests are published.

        manifest_relpaths = list(self._get_relpaths_for_manifests(self.manifest))
        storage_relpaths = {}
        old_relpaths_to_remove = set()

        with StorageDriver.from_storage(self.infra_storage) as driver:
            if isinstance(self.manifest, Container):
                # DONOTMERGE-DONOTMERGE-DONOTMERGE
                #
                # TODO: This it not the right place to handle such logic but it requires
                # more investigation on how this can be handled differently
                for i in range(len(self.manifest.backends)):
                    if isinstance(self.manifest.backends[i], collections.abc.Mapping):
                        continue

                    backend = self.client.load_object_from_url(
                        WildlandObjectType.STORAGE,
                        cast(str, self.manifest.backends[i]),
                        self.manifest.get_publish_user_owner()
                    )

                    # we publish only a single manifest for a storage, under `/.uuid/` path
                    container_manifest = next(
                        self._get_relpaths_for_manifests(self.manifest))

                    relpath = container_manifest.with_name(
                        container_manifest.name.removesuffix('.yaml')
                        + f'.{backend.params["backend-id"]}.yaml'
                    )

                    assert relpath not in storage_relpaths

                    storage_relpaths[relpath] = backend
                    self.manifest.backends[i] = driver.storage_backend.get_url_for_path(relpath)

            # fetch from /.uuid path
            try:
                old_manifest_data = driver.read_file(manifest_relpaths[0])
            except FileNotFoundError:
                pass
            else:
                old_manifest = self.client.session.load_object(old_manifest_data)
                assert issubclass(type(old_manifest), Publishable)

                if not old_manifest.get_unique_publish_id() == self.manifest_unique_id:
                    # we just downloaded this file from manifest_relpaths[0], so
                    # things are very wrong here
                    raise WildlandError(
                        f'old version of manifest at storage '
                        f'{driver.storage.params["backend-id"]} has serious '
                        f'problems; please remove it manually')

                old_relpaths_to_remove.update(set(
                    self._get_relpaths_for_manifests(old_manifest)))

                if isinstance(self.manifest, Container):
                    # DONOTMERGE-DONOTMERGE-DONOTMERGE
                    #
                    # TODO: This it not the right place to handle such logic but it requires
                    # more investigation on how this can be handled differently
                    assert isinstance(old_manifest, Container)

                    for url_or_dict in old_manifest.backends:
                        if isinstance(url_or_dict, collections.abc.Mapping):
                            continue
                        old_relpaths_to_remove.add(
                            driver.storage_backend.get_path_for_url(url_or_dict))

            if just_unpublish:
                old_relpaths_to_remove.update(manifest_relpaths)
                old_relpaths_to_remove.update(storage_relpaths)
            else:
                old_relpaths_to_remove.difference_update(manifest_relpaths)
                old_relpaths_to_remove.difference_update(storage_relpaths)

            # remove /.uuid path last, if present (bool sorts False < True)
            for relpath in sorted(
                    old_relpaths_to_remove,
                    key=(lambda path: path.parts[:2] == ('/', '.uuid'))):
                try:
                    driver.remove_file(relpath)
                except FileNotFoundError:
                    pass

            if not just_unpublish:
                for relpath, storage in storage_relpaths.items():
                    driver.makedirs(relpath.parent)
                    driver.write_file(
                        relpath,
                        self.client.session.dump_object(storage)
                    )

                for relpath in manifest_relpaths:
                    driver.makedirs(relpath.parent)

                    # TODO: This must be refactored together with #379
                    if isinstance(self.manifest, User):
                        data = self.client.session.dump_user(self.manifest)
                    else:
                        assert isinstance(self.manifest, (Container, Storage, Bridge))

                        data = self.client.session.dump_object(self.manifest)

                    driver.write_file(
                        relpath,
                        data
                    )
