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
Wildland core implementation - container-related functions
"""
from pathlib import PurePosixPath, Path
from typing import List, Tuple, Optional, Dict

import wildland.core.core_utils as utils
from wildland.exc import WildlandError
from wildland.log import get_logger
from .wildland_core_api import WildlandCoreApi, ModifyMethod
from .wildland_objects_api import WLContainer, WLObjectType, WLStorage
from .wildland_result import WildlandResult, WLError, wildland_result
from ..client import Client
from ..container import Container
from ..control_client import ControlClientUnableToConnectError
from ..publish import Publisher
from ..storage import Storage
from ..wildland_object.wildland_object import WildlandObject
from ..wlenv import WLEnv
from ..wlpath import WildlandPath

logger = get_logger('core')


class WildlandCoreContainer(WildlandCoreApi):
    """
    Container-related methods of WildlandCore
    """

    def __init__(self, client: Client):
        # info: this is here to stop mypy from complaining about missing params
        self.client = client
        self.env = WLEnv(base_dir=self.client.base_dir)

    def container_create(self, paths: List[str],
                         access_users: Optional[List[str]] = None,
                         encrypt_manifest: bool = True,
                         categories: Optional[List[str]] = None,
                         title: Optional[str] = None, owner: Optional[str] = None,
                         name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[Tuple[WLContainer, Path]]]:
        """
        Create a new container manifest
        :param paths: container paths (must be absolute paths)
        :param access_users: list of additional users who should be able to access this manifest;
        provided as either user fingerprints or WL paths to users.
        Mutually exclusive with encrypt_manifest=False
        :param encrypt_manifest: whether container manifest should be encrypted. Default: True.
        Mutually exclusive with a not-None access_users
        :param categories: list of categories, will be used to generate mount paths
        :param title: title of the container, will be used to generate mount paths
        :param owner: owner of the container; if omitted, default owner will be used
        :param name: name of the container to be created, used in naming container file
        :return: Tuple of WildlandResult and, if successful, the created WLContainer together with
        its path
        """
        return self.__container_create(paths, access_users, encrypt_manifest, categories, title,
                                       owner, name)

    @wildland_result(default_output=None)
    def __container_create(self, paths: List[str],
                           access_users: Optional[List[str]] = None,
                           encrypt_manifest: bool = True,
                           categories: Optional[List[str]] = None,
                           title: Optional[str] = None, owner: Optional[str] = None,
                           name: Optional[str] = None):
        if access_users:
            access_list = []
            for user in access_users:
                if WildlandPath.WLPATH_RE.match(user):
                    # We use canonical form of a Wildland path because we want the whole
                    # path with prefix into manifest
                    access_list.append({"user-path": WildlandPath.get_canonical_form(user)})
                else:
                    result_u, u = self.object_get(WLObjectType.USER, user)
                    if result_u.success and u:
                        access_list.append({'user': u.owner})
        elif not encrypt_manifest:
            access_list = [{'user': '*'}]
        else:
            access_list = []

        owner_result, owner_user = self.object_get(WLObjectType.USER, owner or '@default-owner')
        if not owner_result.success or not owner_user:
            return owner_result, None

        categories = categories if categories else []
        container = Container(
            owner=owner_user.owner,
            paths=[PurePosixPath(p) for p in paths],
            backends=[],
            client=self.client,
            title=title,
            categories=[PurePosixPath(c) for c in categories],
            access=access_list
        )
        path = self.client.save_new_object(WildlandObject.Type.CONTAINER, container, name)
        wl_container = utils.container_to_wlcontainer(container)
        return WildlandResult(), (wl_container, path)

    def container_list(self) -> Tuple[WildlandResult, List[WLContainer]]:
        """
        List all known containers.
        :return: WildlandResult, List of WLContainers
        """
        result = WildlandResult()
        result_list = []
        try:
            for container in self.client.load_all(WildlandObject.Type.CONTAINER):
                result_list.append(utils.container_to_wlcontainer(container))
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
        return result, result_list

    @wildland_result()
    def container_storage_unmount(self, storage_id: int):
        """
        Unmount a storage with given storage id.
        """
        self.client.fs_client.unmount_storage(storage_id)

    def find_container_storage_ids(self, container_id: str) -> Tuple[WildlandResult, List[int]]:
        """
        Unmount container's storages if they are mounted
        """
        result, container = self.container_find_by_id(container_id)
        storage_ids: List[int] = []
        if not result.success or not container:
            return result, storage_ids
        try:
            for mount_path in self.client.fs_client.get_unique_storage_paths(container):
                storage_id, _ = self.client.fs_client.find_storage_id_by_path(
                    mount_path)

                if storage_id:
                    storage_ids.append(storage_id)

                for storage_id in self.client.fs_client.find_all_subcontainers_storage_ids(
                        container):
                    storage_ids.append(storage_id)
        except ControlClientUnableToConnectError:
            pass
        except Exception as e:
            result = WildlandResult()
            result.errors.append(WLError.from_exception(e))
            return result, storage_ids
        return WildlandResult(), storage_ids

    def container_find_backends_usages(self, container_id: str) ->\
            Tuple[WildlandResult, Optional[List[Path]]]:
        """
        Find paths of all container backends
        """
        result, container = self.container_find_by_id(container_id)
        if not result.success or not container:
            return result, None

        storage_paths = []
        for backend in container.load_raw_backends(include_inline=False):
            path = self.client.parse_file_url(backend, container.owner)
            if not path or not path.exists():
                continue
            storage_paths.append(path)

        return WildlandResult(), storage_paths

    def container_has_user_catalog_entries(self, container_id: str) -> \
            Tuple[WildlandResult, Optional[bool]]:
        """
        Check if catalog entry is present in container owner user's manifest
        """
        container_result, container = self.container_find_by_id(container_id)
        if not container_result.success or not container:
            return container_result, None
        user = self.client.load_object_from_name(WildlandObject.Type.USER, container.owner)
        has_catalog_entry = user.has_catalog_entry(self.client.local_url(container.local_path))
        return WildlandResult(), has_catalog_entry

    def container_delete(self, container_id: str, force: bool = False) -> WildlandResult:
        """
        Delete provided container.
        :param container_id: container ID (in the form of user_id:/.uuid/container_uuid)
        :param force: delete even when using local storage manifests; ignore errors on parse
        :return: WildlandResult
        """
        # TODO: also consider detecting user-container link (i.e. user's main container).
        return self.__container_delete(container_id, force)

    @wildland_result(default_output=())
    def __container_delete(self, container_id: str, force: bool = False):
        container_result, container = self.container_find_by_id(container_id)
        if not container_result.success or not container:
            return container_result

        if not container.local_path:
            raise FileNotFoundError('Can only delete a local manifest.')

        user = self.client.load_object_from_name(WildlandObject.Type.USER, container.owner)
        try:
            Publisher(self.client, user).remove_from_cache(container)
        except WildlandError as e:
            logger.warning('Failed to remove container from cache: %s', e)
            if not force:
                logger.debug('Cannot remove container. Set force=True to force deletion.')
            raise e

        logger.debug('Deleting: %s', container.local_path)
        container.local_path.unlink()

        return WildlandResult()

    def container_duplicate(self, container_id: str, name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[Tuple[WLContainer, Path]]]:
        """
        Create a copy of the provided container at the provided friendly name, with a newly
        generated id and copied storages
        :param container_id: id of the container to be duplicated, in the form of
        owner_id:/.uuid/container_uuid
        :param name: optional name for the new container. If omitted, will be generated
        automatically
        :return: Tuple of WildlandResult and, if successful, the created WLContainer together with
        its path
        """
        return self.__container_duplicate(container_id, name)

    @wildland_result(default_output=None)
    def __container_duplicate(self, container_id: str, name: Optional[str]):
        result, container = self.container_find_by_id(container_id)
        if not result.success or not container:
            return result, None
        new_container = container.copy(name)
        path = self.client.save_new_object(WildlandObject.Type.CONTAINER, new_container, name)
        return WildlandResult(), (path, new_container)

    def container_import_from_data(self, yaml_data: str, overwrite: bool = True) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Import container from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param overwrite: if a container of provided uuid already exists, overwrite it;
        default: True. If this is False and the container already exists, this operation will fail.
        :return: tuple of WildlandResult, imported WLContainer (if import was successful)
        """
        raise NotImplementedError

    def container_create_cache(self, container_id: str, storage_template_name: str) \
            -> WildlandResult:
        """
        Create cache storage for a container.
        :param container_id: id of the container (in the form of its publish_path,
        userid:/.uuid/container_uuid)
        :param storage_template_name: use the specified storage template to create a new
        cache storage (becomes primary storage for the container while mounted)
        :return: WildlandResult
        :rtype:
        """
        raise NotImplementedError

    def container_delete_cache(self, container_id: str) -> WildlandResult:
        """
        Delete cache storage for container.
        :param container_id: id of the container (in the form of its publish_path,
        userid:/.uuid/container_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError

    def container_get_storage_cache(self, container_id: str) \
            -> Tuple[WildlandResult, Optional[Storage]]:
        """
        Get cache storage for a container.
        :param container_id: id of the container (in the form of its publish_path,
        userid:/.uuid/container_uuid)
        :return: tuple of WildlandResult and, if successful, the cache storage
        """
        return self.__container_get_storage_cache(container_id)

    @wildland_result(default_output=None)
    def __container_get_storage_cache(self, container_id: str):
        result, container = self.container_find_by_id(container_id)
        if not result.success or not container:
            raise FileNotFoundError(f'Cannot find container {container_id}')

        return self.client.cache_storage(container)

    def container_modify(self, container_id: str, manifest_field: str, operation: ModifyMethod,
                         modify_data: List[str]) -> WildlandResult:
        """
        Modify container manifest
        :param container_id: id of the container to be modified, in the form of
        user_id:/.uuid/container_uuid
        :param manifest_field: field to modify; supports the following:
            - paths
            - categories
            - title
            - access
        :param operation: operation to perform on field ('add', 'delete' or 'set')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """
        raise NotImplementedError

    def container_add_storage(self, container_id: str, storage_names: List[str]) -> WildlandResult:
        """
        Add storages to container
        :param container_id: id of the container to be modified, in the form of
        user_id:/.uuid/container_uuid
        :param storage_names: list of storage names
        :return: WildlandResult
        """
        return self.__container_add_storage(container_id, storage_names)

    @wildland_result()
    def __container_add_storage(self, container_id: str, storage_names: List[str]):
        result, container = self.container_find_by_id(container_id)
        if not result.success or not container:
            raise FileNotFoundError(f'Cannot find container {container_id}')

        if container.local_path is None:
            raise WildlandError('Can only update a local manifest')

        for storage_name in storage_names:
            storage = self.client.load_object_from_name(WildlandObject.Type.STORAGE, storage_name)
            assert storage.local_path
            logger.info('Adding storage: %s', storage.local_path)
            container.add_storage_from_obj(storage, inline=False, storage_name=storage_name)

        self.client.save_object(WildlandObject.Type.CONTAINER, container)

    def container_publish(self, container_id) -> WildlandResult:
        """
        Publish the given container.
        :param container_id: id of the container to be published (user_id:/.uuid/container_uuid)
        :return: WildlandResult
        """
        return self.__container_publish(container_id)

    @wildland_result()
    def __container_publish(self, container_id):
        result, container = self.container_find_by_id(container_id)
        if not result.success or not container:
            raise FileNotFoundError(f'Cannot find container {container_id}')

        try:
            owner_user = self.client.load_object_from_name(WildlandObject.Type.USER,
                                                           container.owner)
            if owner_user.has_catalog:
                logger.info('Publishing container: [%s]', container.get_primary_publish_path())
                publisher = Publisher(self.client, owner_user)
                publisher.publish(container)
        except WildlandError as ex:
            raise WildlandError(f"Failed to publish container: {ex}") from ex

    def container_unpublish(self, container_id) -> WildlandResult:
        """
        Unpublish the given container.
        :param container_id: id of the container to be unpublished (user_id:/.uuid/container_uuid)
        :return: WildlandResult
        """
        return self.__container_unpublish(container_id)

    @wildland_result()
    def __container_unpublish(self, container_id):
        result, container = self.container_find_by_id(container_id)
        if not result.success or not container:
            raise FileNotFoundError(f'Cannot find container {container_id}')

        try:
            owner_user = self.client.load_object_from_name(WildlandObject.Type.USER,
                                                           container.owner)
            logger.info('Unpublishing container: [%s]', container.get_primary_publish_path())
            publisher = Publisher(self.client, owner_user)
            publisher.unpublish(container)
        except WildlandError as ex:
            raise WildlandError(f"Failed to unpublish container: {ex}") from ex

    def container_find_by_path(self, path: str) -> \
            Tuple[WildlandResult, List[Tuple[WLContainer, WLStorage]]]:
        """
        Find container by path relative to Wildland mount root.
        :param path: path to file (relative to Wildland mount root)
        :return: tuple of WildlandResult and list of tuples of WLContainer, WLStorage that contain
        the provided path
        """
        return self.__container_find_by_path(path)

    @wildland_result(default_output=None)
    def __container_find_by_path(self, _path: str):
        fs_client = self.client.fs_client
        path = fs_client.mount_dir / _path
        if not path.exists():
            raise FileNotFoundError(f'Given path [{path}] does not exist.')

        try:
            relpath = path.resolve().relative_to(fs_client.mount_dir)
        except ValueError as e:
            raise WildlandError(f'Given path [{path}] is not a subpath of the mountpoint '
                                f'[{fs_client.mount_dir}]') from e

        if path.is_dir():
            results = fs_client.run_control_command('dirinfo', path=('/' + str(relpath)))
        else:
            results = [fs_client.run_control_command('fileinfo', path=('/' + str(relpath)))]

        response: Dict[str, Tuple[WLContainer, WLStorage]] = {}

        def get_index(wl_c: WLContainer, wl_s: WLStorage):
            return f'{wl_c.owner}:{wl_c.id}:{wl_s.backend_id}'

        for result in results:
            if not result:
                continue
            name = f"{result['storage']['owner']}:{result['storage']['container-path']}:"
            container = self.client.load_object_from_name(WildlandObject.Type.CONTAINER, name)
            if not isinstance(container, Container):
                continue
            for storage in container.load_storages():
                if storage.backend_id != result['storage']['backend-id']:
                    continue
                wl_container = utils.container_to_wlcontainer(container)
                wl_storage = utils.storage_to_wl_storage(storage)
                if response.get(get_index(wl_container, wl_storage)) is not None:
                    continue
                response[get_index(wl_container, wl_storage)] = (wl_container, wl_storage)
                break

        response_list = [response[idx] for idx in response]
        if not response_list:
            raise WildlandError('Given path was not found in any storage')

        return response_list

    def container_find_by_id(self, container_id: str) \
            -> Tuple[WildlandResult, Optional[Container]]:
        """
        Find container by id.
        :param container_id: id of the container to be found (user_id:/.uuid/container_uuid)
        :return: tuple of WildlandResult and, if successful, the Container
        """

        result = WildlandResult()

        for container in self.client.load_all(WildlandObject.Type.CONTAINER):
            if utils.container_to_wlcontainer(container).id == container_id:
                return result, container

        container = self.client.load_object_from_name(WildlandObject.Type.CONTAINER, container_id)
        if container and utils.container_to_wlcontainer(container).id == container_id:
            return result, container

        result.errors.append(
            WLError.from_exception(FileNotFoundError(f'Cannot find container {container_id}')))
        return result, None
