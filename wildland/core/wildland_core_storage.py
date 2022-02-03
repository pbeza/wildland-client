# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
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
Wildland core implementation - storage-related functions
"""
import uuid
from typing import List, Tuple, Optional, Dict, Type, Any

import wildland.core.core_utils as utils
from wildland.log import get_logger
from .wildland_core_api import WildlandCoreApi, ModifyMethod
from .wildland_objects_api import WLStorage, WLStorageBackend
from .wildland_result import WildlandResult, wildland_result
from ..client import Client
from ..exc import WildlandError
from ..storage import Storage
from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..wildland_object.wildland_object import WildlandObject
from ..wlenv import WLEnv
from ..wlpath import WildlandPath

logger = get_logger('core-storage')


def get_backend(backend_type: str) -> Type[StorageBackend]:
    backends = get_storage_backends()
    backend = backends.get(backend_type)
    if backend is None:
        raise FileNotFoundError(f'[{backend_type}] cannot be matched with any known storage '
                                f'configuration')
    return backend


class WildlandCoreStorage(WildlandCoreApi):
    """
    Storage-related methods of WildlandCore
    """

    def __init__(self, client: Client):
        # info: this is here to stop mypy from complaining about missing params
        self.client = client
        self.env = WLEnv(base_dir=self.client.base_dir)

    def supported_storage_backends(self) -> Tuple[WildlandResult, List[WLStorageBackend]]:
        """
        List all supported storage backends.
        :return: WildlandResult and a list of supported storage backends.
        """
        raise NotImplementedError

    def storage_create(self, backend_type: str, backend_params: Dict[str, Any],
                       container_id: str, name: Optional[str], trusted: bool = False,
                       watcher_interval: Optional[int] = 0, inline: bool = True,
                       access_users: Optional[list[str]] = None, encrypt_manifest: bool = True) -> \
            Tuple[WildlandResult, Optional[WLStorage]]:
        """
        Create a storage.
        :param backend_type: storage type
        :param backend_params: params for the given backend as a dict of param_name, param_value.
        They must conform to parameter names as provided by supported_storage_backends
        :param container_id: container this storage is for
        :param name: name of the storage to be created, used in naming storage file
        :param trusted: should the storage be trusted
        :param watcher_interval: set the storage watcher-interval in seconds
        :param inline: Add the storage directly to container manifest,
        instead of saving it to a file
        :param access_users: limit access to this storage to the users provided here as either
        user fingerprints or WL paths to users.
        Default: same as the container
        :param encrypt_manifest: should the storage manifest be encrypted. If this is False,
        access_users should be None. The container manifest itself might also be encrypted or not,
        this does not change its settings.
        :return: Tuple of WildlandResult and, if creation was successful, WLStorage that was
        created
        """
        return self.__storage_create(backend_type, backend_params, container_id, name, trusted,
                                     watcher_interval, inline, access_users, encrypt_manifest)

    def __get_container_from_wl_container_id(self, container_id):
        # FIXME:
        for container in self.client.load_all(WildlandObject.Type.CONTAINER):
            if utils.container_to_wlcontainer(container).id == container_id:
                return container

        raise FileNotFoundError(f'Cannot find container {container_id}')

    @wildland_result(default_output=None)
    def __storage_create(self, backend_type: str, backend_params: Dict[str, Any],
                         container_id: str, name: Optional[str], trusted: bool = False,
                         watcher_interval: Optional[int] = 0, inline: bool = True,
                         access_users: Optional[list[str]] = None, encrypt_manifest: bool = True):

        container = self.__get_container_from_wl_container_id(container_id)
        if not container.local_path:
            raise WildlandError('Need a local container')

        container_mount_path = container.paths[0]
        logger.info('Using container: %s (%s)', str(container.local_path),
                    str(container_mount_path))
        backend = get_backend(backend_type)

        # remove default, non-required values
        for param, value in list(backend_params.items()):
            if value is None or value == []:
                del backend_params[param]

        backend.validate_params(backend_params)

        if watcher_interval:
            backend_params['watcher-interval'] = watcher_interval

        backend_params['backend-id'] = str(uuid.uuid4())

        access = None

        if not encrypt_manifest:
            access = [{'user': '*'}]
        elif access_users:
            access = []
            for a in access_users:
                if WildlandPath.WLPATH_RE.match(a):
                    access.append({'user-path': WildlandPath.get_canonical_form(a)})
                else:
                    access.append({'user': self.client.load_object_from_name(
                        WildlandObject.Type.USER, a).owner})
        elif container.access:
            access = container.access

        backend_params['type'] = backend.TYPE

        storage = Storage(
            storage_type=backend.TYPE,
            owner=container.owner,
            container=container,
            params=backend_params,
            client=self.client,
            trusted=backend_params.get('trusted', trusted),
            access=access
        )
        storage.validate()
        # try to load storage from params to check if everything is ok,
        # e.g., reference container is available
        self.client.load_object_from_url_or_dict(WildlandObject.Type.STORAGE,
                                                 storage.to_manifest_fields(inline=False),
                                                 storage.owner, container=container)
        logger.info('Adding storage %s to container.', storage.backend_id)
        self.client.add_storage_to_container(container, [storage], inline, name)
        logger.info('Saved container %s', str(container.local_path))

        return utils.storage_to_wl_storage(storage)

    def storage_create_from_template(self, template_name: str, container_id: str,
                                     local_dir: Optional[str] = None):
        """
        Create storages for a container from a given storage template.
        :param template_name: name of the template
        :param container_id: container this storage is for
        :param local_dir: str to be passed to template renderer as a parameter, can be used by
        template creators
        """
        raise NotImplementedError

    def storage_list(self) -> Tuple[WildlandResult, List[WLStorage]]:
        """
        List all known storages.
        :return: WildlandResult, List of WLStorages
        """
        raise NotImplementedError

    def storage_delete(self, storage_id: str, cascade: bool = True,
                       force: bool = False) -> WildlandResult:
        """
        Delete provided storage.
        :param storage_id: storage ID
         (in the form of user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :param cascade: remove reference from containers
        :param force: delete even if used by containers or if manifest cannot be loaded
        :return: WildlandResult
        """
        raise NotImplementedError

    def storage_import_from_data(self, yaml_data: str, overwrite: bool = True) -> \
            Tuple[WildlandResult, Optional[WLStorage]]:
        """
        Import storage from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param overwrite: if a storage of provided uuid already exists in the appropriate container,
        overwrite it; default: True. If this is False and the storage already exists, this
         operation will fail.
        :return: tuple of WildlandResult, imported WLStorage (if import was successful)
        """
        raise NotImplementedError

    def storage_modify(self, storage_id: str, manifest_field: str, operation: ModifyMethod,
                       modify_data: List[str]) -> WildlandResult:
        """
        Modify storage manifest
        :param storage_id: id of the storage to be modified, in the form of
        user_id:/.uuid/container_uuid:/.uuid/storage_uuid
        :param manifest_field: field to modify; supports the following:
            - location
            - access
        :param operation: operation to perform on field ('add', 'delete' or 'set')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """
        raise NotImplementedError

    def storage_publish(self, storage_id) -> WildlandResult:
        """
        Publish the given storage.
        :param storage_id: id of the storage to be published
         (user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError

    def storage_unpublish(self, storage_id) -> WildlandResult:
        """
        Unpublish the given storage.
        :param storage_id: id of the storage to be unpublished
         (user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError
