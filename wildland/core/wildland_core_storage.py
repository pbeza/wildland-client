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
from pathlib import Path, PurePosixPath
from typing import List, Tuple, Optional, Dict, Type, Any, Union, Iterable

import wildland.core.core_utils as utils
from wildland.log import get_logger
from .wildland_core_api import WildlandCoreApi, ModifyMethod
from .wildland_objects_api import WLStorage, WLStorageBackend
from .wildland_result import WildlandResult, wildland_result, WLError, WLErrorType
from ..client import Client
from ..container import Container
from ..exc import WildlandError
from ..manifest.manifest import ManifestError
from ..manifest.template import StorageTemplate, TemplateManager
from ..publish import Publisher
from ..storage import Storage
from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..storage_sync.base import SyncState
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
                       access_users: Optional[List[str]] = None, encrypt_manifest: bool = True) -> \
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

    @wildland_result(default_output=None)
    def __storage_create(self, backend_type: str, backend_params: Dict[str, Any],
                         container_id: str, name: Optional[str], trusted: bool = False,
                         watcher_interval: Optional[int] = 0, inline: bool = True,
                         access_users: Optional[List[str]] = None, encrypt_manifest: bool = True):

        container = self.__get_container_from_wl_container_id(container_id)
        if not container.local_path:
            raise WildlandError('Need a local container')

        container_mount_path = container.paths[0]
        logger.info('Using container: %s (%s)', str(container.local_path),
                    str(container_mount_path))
        backend = get_backend(backend_type)

        backend_params = backend.validate_and_parse_params(backend_params)

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

    def __get_container_from_wl_container_id(self, container_id):
        # FIXME:
        for container in self.client.load_all(WildlandObject.Type.CONTAINER):
            if utils.container_to_wlcontainer(container, self.client).id == container_id:
                return container

        raise FileNotFoundError(f'Cannot find container {container_id}')

    def storage_create_from_template(self, template_name: str,
                                     container_id: str, no_publish: bool,
                                     local_dir: Optional[str] = None) -> WildlandResult:
        """
        Create storages for a container from a given storage template.
        :param template_name: name of the template
        :param container_id: container this storage is for
        :param no_publish: flag whether publish template
        :param local_dir: str to be passed to template renderer as a parameter, can be used by
        template creators
        """
        return self.__storage_create_from_template(template_name, container_id, local_dir, no_publish)

    @wildland_result()
    def __storage_create_from_template(self, template_name: str, container_id: str,
                                       local_dir: Optional[str], no_publish: bool):
        # TODO change this block after #699 is resolved and use container_find_by_id from wl_core_api
        container = None
        for _container in self.client.load_all(WildlandObject.Type.CONTAINER):
            if utils.container_to_wlcontainer(_container, self.client).id == container_id:
                container = _container
        # TODO END

        if not container:
            return WildlandResult()
        template_manager = TemplateManager(self.client.dirs[WildlandObject.Type.TEMPLATE])
        storage_templates = template_manager.get_template_file_by_name(template_name).templates
        result = self.storage_do_create_from_template(container, storage_templates, local_dir, no_publish)
        return result

    # TODO change container: Container to container_id: str and adjust code, after
    # TODO https://gitlab.com/wildland/wildland-client/-/issues/699 &&
    # TODO and https://gitlab.com/wildland/wildland-client/-/issues/702 are solved
    def storage_do_create_from_template(self, container: Container,
                                        storage_templates: Iterable[StorageTemplate],
                                        local_dir: Optional[str],
                                        no_publish: bool = False) -> WildlandResult:
        return self.__storage_do_create_from_template(container, storage_templates, local_dir, no_publish)

    @wildland_result()
    def __storage_do_create_from_template(self, container: Container,
                                          storage_templates: Iterable[StorageTemplate],
                                          local_dir: Optional[str],
                                          no_publish: bool = False):
        result = WildlandResult()
        
        to_process: List[Tuple[Storage, StorageBackend]] = []

        for template in storage_templates:
            try:
                storage = template.get_storage(self.client, container, local_dir)
            except ValueError as ex:
                result.errors.append(WLError.from_exception(ex))
                return result

            storage_backend = StorageBackend.from_params(storage.params)
            to_process.append((storage, storage_backend))

        storages_to_add = []
        for storage, backend in to_process:
            if storage.is_writeable:
                self.__ensure_backend_location_exists(backend)
            storages_to_add.append(storage)
            logger.info(f'Adding storage {storage.backend_id} to container.')

        self.client.add_storage_to_container(container=container, storages=storages_to_add, inline=True)
        logger.info(f'Saved container {container.local_path}')

        if not no_publish:
            try:
                user = self.client.load_object_from_name(WildlandObject.Type.USER, container.owner)
                Publisher(self.client, user).republish(container)
            except WildlandError as ex:
                result.errors.append(WLError.from_exception(WildlandError(f"Failed to republish container: {ex}")))

        return result

    def __ensure_backend_location_exists(self, backend: StorageBackend) -> None:
        path = backend.location

        if path is None:
            return
        try:
            with backend:
                if str(PurePosixPath(backend.location)) != backend.location:
                    raise WildlandError('The `LOCATION_PARAM` of the backend is not a valid path.')
                backend.mkdir(PurePosixPath(path))
                logger.info(f'Created base path: {path}')
        except Exception as ex:
            logger.warning('Could not create base path %s in a writable storage [%s]. %s',
                           path, backend.backend_id, ex)
    
    def storage_list(self) -> Tuple[WildlandResult, List[WLStorage]]:
        """
        List all known storages.
        :return: WildlandResult, List of WLStorages
        """
        return self.__storage_list()

    @wildland_result(default_output=[])
    def __storage_list(self):
        result = WildlandResult()
        storages = []
        try:
            for storage in self.client.load_all(WildlandObject.Type.STORAGE):
                storages.append(utils.storage_to_wl_storage(storage))
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
        return result, storages

    def storage_delete(self, name: str, cascade: bool = True,
                       force: bool = False) -> WildlandResult:
        """
        Delete provided storage.
        :param name: storage name
         (in the form of user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :param cascade: remove reference from containers
        :param force: delete even if used by containers or if manifest cannot be loaded
        :return: WildlandResult
        """
        return self.__storage_delete(name, cascade, force)

    @wildland_result()
    def __storage_delete(self, name: str, cascade: bool, force: bool):
        delete_result = WildlandResult()
        result, local_path, usages = self.storage_get_local_path_and_find_usages(name)

        if WLErrorType.MANIFEST_ERROR in [err.error_code for err in result.errors]:
            if force:
                logger.info('Failed to load manifest: %s', str(result))
                self.__storage_delete_force(name, cascade)
                return delete_result

            logger.info('Failed to load manifest, cannot delete: %s', str(result))
            logger.info('Use --force to force deletion.')
            delete_result.errors += result.errors
            return delete_result

        self.__storage_sync_containers(name, usages, force)

        if local_path:
            if cascade:
                delete_cascade_result = self.__storage_delete_cascade(usages)
                delete_result.errors += delete_cascade_result.errors
            else:
                for container, _ in usages:
                    logger.info('Storage used in container: %s', container.local_path)

            if usages and not force and not cascade:
                delete_result.errors.append(
                    WLError.from_exception(
                        WildlandError('Storage is still used, not deleting '
                                      '(use --force or remove --no-cascade)')))
                return delete_result

            logger.info('Deleting: %s', local_path)
            local_path.unlink()
            return delete_result

        if not cascade:
            delete_result.errors.append(WLError.from_exception(
                WildlandError('Inline storage cannot be deleted in --no-cascade mode')))
            return delete_result

        delete_cascade_result = self.__storage_delete_cascade(usages)
        delete_result.errors += delete_cascade_result.errors

        return delete_result

    def storage_get_local_path_and_find_usages(self, name: str) \
            -> Tuple[WildlandResult, Optional[Path],
                     Optional[List[Tuple[Container, Union[Path, str]]]]]:
        return self.__storage_get_local_path_and_find_usages(name)

    @wildland_result(default_output=None)
    def __storage_get_local_path_and_find_usages(self, name: str):
        result = WildlandResult()
        try:
            storage = self.client.load_object_from_name(WildlandObject.Type.STORAGE, name)

        except ManifestError as me:
            result.errors.append(WLError.from_exception(ManifestError(me)))
            return result, None, None

        except WildlandError as we:
            used_by = self.client.find_storage_usage(name)
            if not used_by:
                result.errors.append(WLError.from_exception(WildlandError(we)))
                return result, None, None
            return result, None, used_by

        if not storage.local_path:
            result.errors.append(WLError.from_exception(
                WildlandError('Can only delete a local manifest')))
            return result, None, None
        used_by = self.client.find_storage_usage(storage.backend_id)
        return result, storage.local_path, used_by

    def storage_get_usages_within_container(
            self,
            usages: Tuple[Optional[Path], Optional[List[Tuple[Container, Union[Path, str]]]]],
            container_name: str
    ):
        container_obj = self.client.load_object_from_name(
            WildlandObject.Type.CONTAINER, container_name)
        usages = [(cont, backend) for (cont, backend) in usages
                  if cont.local_path == container_obj.local_path]

        return usages

    def __storage_delete_force(self, name: str, cascade: bool):
        try:
            path = self.client.find_local_manifest(WildlandObject.Type.STORAGE, name)
            if path:
                logger.info('Deleting file %s', path)
                path.unlink()
        except ManifestError:
            # already removed
            pass
        if cascade:
            logger.warning('Unable to cascade remove: manifest failed to load.')

    def __storage_sync_containers(self,
                                  name: str,
                                  used_by: List[Tuple[Container, Union[Path, str]]],
                                  force: bool):
        container_to_sync = []
        container_failed_to_sync = []
        for container_obj, _ in used_by:
            if len(self.client.get_all_storages(container_obj)) > 1 and not force:
                status = self.client.get_sync_job_state(container_obj.sync_id)
                if status is None:
                    container_to_sync.append(container_obj)
                elif status[0] != SyncState.SYNCED:
                    logger.info('Syncing of %s is in progress.', container_obj.uuid)
                    return

        for c in container_to_sync:
            storage_to_delete = self.client.get_storage_by_id_or_type(name,
                                                                      self.client.all_storages(c))
            logger.info('Outdated storage for container %s, attempting to sync storage.', c.uuid)
            target = None
            try:
                target = self.client.get_remote_storage(c, excluded_storage=name)
            except WildlandError:
                pass
            if not target:
                target = self.client.get_local_storage(c, excluded_storage=name)

            logger.debug("sync: {%s} -> {%s}", storage_to_delete, target)
            response = self.client.do_sync(c.uuid, c.sync_id, storage_to_delete.params,
                                           target.params, one_shot=True, unidir=True)
            logger.debug(response)
            msg, success = self.client.wait_for_sync(c.sync_id)
            logger.info(msg)
            if not success:
                container_failed_to_sync.append(c.uuid)

        if container_failed_to_sync and not force:
            logger.info('Failed to sync storage for containers: %s',
                        ','.join(container_failed_to_sync))

    def storage_delete_cascade(self,
                               containers: List[Tuple[Container,
                                                      Union[Path, str]]]) -> WildlandResult:
        return self.__storage_delete_cascade(containers)

    @wildland_result()
    def __storage_delete_cascade(self, containers: List[Tuple[Container, Union[Path, str]]]):
        result = WildlandResult()
        for container, backend in containers:
            logger.info('Removing %s from %s', backend, container.local_path)
            container.del_storage(backend)
            try:
                logger.info('Saving: %s', container.local_path)
                self.client.save_object(WildlandObject.Type.CONTAINER, container)
            except ManifestError as ex:
                result.errors.append(WLError.from_exception(ex))
        return result

    def storage_get_by_id(self, storage_id: str) -> Tuple[WildlandResult, Optional[Storage]]:
        return self.__storage_get_by_id(storage_id)

    @wildland_result(default_output=None)
    def __storage_get_by_id(self, storage_id: str):
        result = WildlandResult()

        for storage in self.client.load_all(WildlandObject.Type.STORAGE):
            if utils.storage_to_wl_storage(storage).id == storage_id:
                return result, storage

        result.errors.append(
            WLError.from_exception(FileNotFoundError(f'Cannot find storage {storage_id}')))
        return result, None

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
