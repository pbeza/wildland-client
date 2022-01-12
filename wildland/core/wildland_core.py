# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
Wildland core implementation
"""
from typing import List, Tuple, Optional, Callable, Dict
from pathlib import PurePosixPath, Path

import wildland.core.core_utils as utils
from wildland.manifest.manifest import Manifest

from .wildland_core_api import WildlandCoreApi, ModifyMethod
from .wildland_result import WildlandResult, WLError, wildland_result
from ..bridge import Bridge
from ..client import Client
from ..container import Container
from ..log import get_logger
from ..storage import Storage
from ..user import User
from ..link import Link
from ..wildland_object.wildland_object import WildlandObject
from .wildland_objects_api import WLBridge, WLStorageBackend, WLStorage, WLContainer, \
    WLObject, WLTemplateFile, WLObjectType
from ..wlenv import WLEnv
from .wildland_core_user import WildlandCoreUser
from .wildland_core_container import WildlandCoreContainer

logger = get_logger('core')

# Style goal: All methods must be <15 functional lines of code; if more, refactor

# TODO: core should have its own tests, possibly test_cli should be remade to test WildlandCore, and
# TODO cli should get its own, simple tests with mocked methods


class WildlandCore(WildlandCoreContainer, WildlandCoreUser, WildlandCoreApi):
    """Wildland Core implementation"""

    # All user-facing methods should be wrapped in wildland_result or otherwise assure
    # they wrap all exceptions in WildlandResult
    def __init__(self, client: Client):
        # TODO: once cli is decoupled from client, this should take more raw params and initialize
        # config somewhat better
        super().__init__(client)
        self.client = client
        self.env = WLEnv(base_dir=self.client.base_dir)

    # GENERAL METHODS
    def object_info(self, yaml_data: str) -> Tuple[WildlandResult, Optional[WLObject]]:
        """
        This method parses yaml data and returns an appropriate WLObject; to perform any further
        operations the object has to be imported.
        :param yaml_data: yaml string with object data; the data has to be signed correctly
        :return: WildlandResult and WLObject of appropriate type
        """
        return self.__object_info(yaml_data)

    @wildland_result
    def __object_info(self, yaml_data):
        obj = self.client.load_object_from_bytes(None, yaml_data.encode())
        if isinstance(obj, User):
            return utils.user_to_wluser(obj, self.client)
        if isinstance(obj, Container):
            return utils.container_to_wlcontainer(obj)
        if isinstance(obj, Bridge):
            return utils.bridge_to_wl_bridge(obj)
        if isinstance(obj, Storage):
            return utils.storage_to_wl_storage(obj)
        result = WildlandResult()
        error = WLError(error_code=700, error_description="Unknown object type encountered",
                        is_recoverable=False, offender_type=None, offender_id=None,
                        diagnostic_info=yaml_data)
        result.errors.append(error)
        return result, None

    def object_sign(self, object_data: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Sign Wildland manifest data.
        :param object_data: object data to sign.
        :return: tuple of WildlandResult and string data (if signing was successful)
        """
        raise NotImplementedError

    def object_verify(self, object_data: str, verify_signature: bool = True) -> WildlandResult:
        """
        Verify if the data provided is a correct Wildland object manifest.
        :param object_data: object data to verify
        :param verify_signature: should we also check if the signature is correct; default: True
        :rtype: WildlandResult
        """
        raise NotImplementedError

    def object_export(self, object_type: WLObjectType, object_id: str, decrypt: bool = True) -> \
            Tuple[WildlandResult, Optional[str]]:
        """
        Get raw object manifest
        :param object_id: object_id of the object
        :param object_type: type of the object
        :param decrypt: should the manifest be decrypted as much as possible
        """
        raise NotImplementedError

    def object_check_published(self, object_type: WLObjectType, object_id: str) -> \
            Tuple[WildlandResult, Optional[bool]]:
        """
        Check if provided object is published.
        :param object_id: object_id of the object
        :param object_type: type of the object
        :return: tuple of WildlandResult and publish status, if available
        :rtype:
        """
        raise NotImplementedError

    def object_get_local_path(self, object_type: WLObjectType, object_id: str) -> \
            Tuple[WildlandResult, Optional[str]]:
        """
        Return local path to object, if available.
        :param object_id: object_id of the object
        :param object_type: type of the object
        :return: tuple of WildlandResult and local file path or equivalent, if available
        """
        return self._object_get_local_path(object_type, object_id)

    @wildland_result()
    def _object_get_local_path(self, object_type: WLObjectType, object_id: str):
        result = WildlandResult()
        obj_type = utils.wl_obj_to_wildland_object_type(object_type)
        if not obj_type:
            result.errors.append(WLError(700, "Unknown object type", False, object_type, object_id))
            return result, None

        for obj in self.client.load_all(obj_type):
            if utils.get_object_id(obj) == object_id:
                return result, str(obj.local_path)
        return result, None

    def object_update(self, updated_object: WLObject) -> Tuple[WildlandResult, Optional[str]]:
        """
        Perform a batch of upgrades on an object. Currently just able to replace an existing object
        of a given ID, regardless of its previous state, but in the future it should take note
        of explicit manifest versioning and reject any changes that are performed on an obsolete
        version.
        :param updated_object: Any WLObject
        :return: Wildland Result determining whether change was successful and, if it was, id of
        the modified object
        """
        raise NotImplementedError

    def object_get(self, object_type: WLObjectType, object_name: str) -> \
            Tuple[WildlandResult, Optional[WLObject]]:
        """
        Find provided WL object.
        :param object_name: name of the object: can be the file name or user fingerprint or URL
         (but not local path - in case of local path object should be loaded by object_info)
        :param object_type: type of the object
        :return: tuple of WildlandResult and object, if found
        """
        return self.__object_get(object_type, object_name)

    @wildland_result(default_output=None)
    def __object_get(self, object_type: WLObjectType, object_name: str):
        obj_type = utils.wl_obj_to_wildland_object_type(object_type)
        assert obj_type
        wildland_object = self.client.load_object_from_name(obj_type, object_name)
        if object_type == WLObjectType.USER:
            return utils.user_to_wluser(wildland_object, self.client)
        if object_type == WLObjectType.CONTAINER:
            return utils.container_to_wlcontainer(wildland_object)
        if object_type == WLObjectType.BRIDGE:
            return utils.bridge_to_wl_bridge(wildland_object)
        if object_type == WLObjectType.STORAGE:
            return utils.storage_to_wl_storage(wildland_object)
        return None

    def object_import_from_yaml(self, yaml_data: bytes, object_name: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLObject]]:
        """
        Import object from raw data. Only copies the provided object to appropriate WL manifest
        directory, does not create any bridges or other objects.
        :param yaml_data: bytes with yaml manifest data; must be correctly signed
        :param object_name: name of the object to be created; if not provided, will be generated
        automatically
        """

        return self.__object_import_from_yaml(yaml_data, object_name)

    @wildland_result(default_output=None)
    def __object_import_from_yaml(self, yaml_data: bytes, object_name: Optional[str]):
        Manifest.verify_and_load_pubkeys(yaml_data, self.client.session.sig)

        obj: WildlandObject = self.client.load_object_from_bytes(None, data=yaml_data)
        return self._do_import(obj, object_name)

    def object_import_from_url(self, url: str, object_name: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLObject]]:
        """
        Import object from raw data. Only copies the provided object to appropriate WL manifest
        directory, does not create any bridges or other objects.
        :param url: url to object manifest
        :param object_name: name of the object to be created
        """
        return self.__object_import_from_url(url, object_name)

    @wildland_result(default_output=None)
    def __object_import_from_url(self, url: str, object_name: Optional[str]):
        _, default_user = self.env.get_default_user()
        if not default_user:
            default_user = ''

        obj: WildlandObject = self.client.load_object_from_url(None, url, default_user)
        return self._do_import(obj, object_name)

    def _do_import(self, obj: WildlandObject, name: Optional[str]):
        if utils.check_object_existence(obj, self.client):
            raise FileExistsError(utils.get_object_id(obj))
        path = self.client.save_new_object(obj.type, obj, name, enforce_original_bytes=True)
        logger.info('Created: %s', path)
        return utils.wildland_object_to_wl_object(obj, self.client)

    def put_file(self, local_file_path: str, wl_path: str) -> WildlandResult:
        """
        Put a file under Wildland path
        :param local_file_path: path to local file
        :param wl_path: Wildland path
        :return: WildlandResult
        """
        raise NotImplementedError

    def put_data(self, data_bytes: bytes, wl_path: str) -> WildlandResult:
        """
        Put a file under Wildland path
        :param data_bytes: bytes to put in the provided location
        :param wl_path: Wildland path
        :return: WildlandResult
        """
        raise NotImplementedError

    def get_file(self, local_file_path: str, wl_path: str) -> WildlandResult:
        """
        Get a file, given its Wildland path. Saves to a file.
        :param local_file_path: path to local file
        :param wl_path: Wildland path
        :return: WildlandResult
        """
        raise NotImplementedError

    def get_data(self, wl_path: str) -> Tuple[WildlandResult, Optional[bytes]]:
        """
        Get a file, given its Wildland path. Returns data.
        :param wl_path: Wildland path
        :return: Tuple of WildlandResult and bytes (if successful)
        """
        raise NotImplementedError

    def start_wl(self, remount: bool = False, single_threaded: bool = False,
                 default_user: Optional[str] = None,
                 callback: Callable[[WLContainer], None] = None) -> WildlandResult:
        """
        Mount the Wildland filesystem into config's mount_dir.
        :param remount: if mounted already, remount
        :param single_threaded: run single-threaded
        :param default_user: specify a default user to be used
        :param callback: a function from WLContainer to None that will be called before each
         mounted container
        :return: WildlandResult
        """
        raise NotImplementedError

    def stop_wl(self) -> WildlandResult:
        """
        Unmount the Wildland filesystem.
        """
        raise NotImplementedError

    # BRIDGES
    def bridge_create(self, paths: Optional[List[str]], owner: Optional[str] = None,
                      target_user: Optional[str] = None, user_url: Optional[str] = None,
                      name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Create a new bridge. At least one from target_user, user_url must be provided.
        :param paths: paths for user in owner namespace (if None, will be taken from user manifest)
        :param owner: user_id for the owner of the created bridge
        :param target_user: user_id to whom the bridge will point. If provided, will be used to
        verify the integrity of the target_user_url
        :param user_url: path to the user manifest (use file:// for local file). If target_user
        is provided, their user manifest will be first located in their manifests catalog, and only
        as a second choice from this url.
        If target_user is skipped, the user manifest from this path is considered trusted.
        :param name: optional name for the newly created bridge. If omitted, will be generated
        automatically
        :return: tuple of WildlandResult and, if successful, the created WLBridge
        """

        return self.__bridge_create(paths, owner, target_user, user_url, name)

    @wildland_result(default_output=None)
    def __bridge_create(self, paths: Optional[List[str]], owner: Optional[str] = None,
                        target_user: Optional[str] = None, user_url: Optional[str] = None,
                        name: Optional[str] = None):

        if not target_user and not user_url:
            raise ValueError('Bridge creation requires at least one of: target user id, target '
                             'user url.')
        if user_url and not self.client.is_url(user_url):
            user_url = self.client.local_url(Path(user_url))
            if not self.client.is_url(user_url):
                raise ValueError('Bridge requires user URL')

        if not owner:
            _, owner = self.env.get_default_owner()

        assert owner

        owner_user = self.client.load_object_from_name(WildlandObject.Type.USER, owner)

        if target_user:
            target_user_object = self.client.load_object_from_name(
                WildlandObject.Type.USER, target_user)
        else:
            assert user_url
            target_user_object = self.client.load_object_from_url(
                WildlandObject.Type.USER, user_url, owner=owner_user.owner,
                expected_owner=target_user)

        found_manifest = self.client.find_user_manifest_within_catalog(target_user_object)

        if not found_manifest:
            if user_url and not self.client.is_local_url(user_url):
                location = user_url
            elif target_user_object.local_path:
                logger.debug('Cannot find user manifest in manifests catalog. Using local file '
                             'path.')
                location = self.client.local_url(target_user_object.local_path)
            elif user_url:
                location = user_url
            else:
                raise FileNotFoundError('User manifest not found in manifests catalog. '
                                        'Provide explicit url.')
        else:
            storage, file = found_manifest
            file = '/' / file
            location_link = Link(file, client=self.client, storage=storage)
            location = location_link.to_manifest_fields(inline=True)

        fingerprint = self.client.session.sig.fingerprint(target_user_object.primary_pubkey)

        if paths:
            bridge_paths = [PurePosixPath(p) for p in paths]
        else:
            bridge_paths = Bridge.create_safe_bridge_paths(fingerprint, target_user_object.paths)
            logger.debug(
                "Using user's default paths: %s", [str(p) for p in target_user_object.paths])

        bridge = Bridge(
            owner=owner_user.owner,
            user_location=location,
            user_pubkey=target_user_object.primary_pubkey,
            user_id=fingerprint,
            paths=bridge_paths,
            client=self.client
        )

        if not name and paths:
            # an heuristic for nicer paths
            for path in paths:
                if 'uuid' not in str(path):
                    name = str(path).lstrip('/').replace('/', '_')
                    break
        path = self.client.save_new_object(WildlandObject.Type.BRIDGE, bridge, name)
        logger.info("Created: %s", path)
        return utils.bridge_to_wl_bridge(bridge)

    def bridge_list(self) -> Tuple[WildlandResult, List[WLBridge]]:
        """
        List all known bridges.
        :return: WildlandResult, List of WLBridges
        """
        result = WildlandResult()
        result_list = []
        try:
            for bridge in self.client.load_all(WildlandObject.Type.BRIDGE):
                result_list.append(utils.bridge_to_wl_bridge(bridge))
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
        return result, result_list

    def bridge_delete(self, bridge_id: str) -> WildlandResult:
        """
        Delete provided bridge.
        :param bridge_id: Bridge ID (in the form of user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        return self.__bridge_delete(bridge_id)

    @wildland_result(default_output=())
    def __bridge_delete(self, bridge_id: str):
        for bridge in self.client.load_all(WildlandObject.Type.BRIDGE):
            if utils.get_object_id(bridge) == bridge_id:
                bridge.local_path.unlink()
                return
        raise FileNotFoundError(f'Cannot find bridge {bridge_id}')

    def bridge_import(self, path_or_url: str, paths: List[str], object_owner: Optional[str],
                      only_first: bool = False) -> Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Import bridge from provided url or path.
        :param path_or_url: WL path, local path or URL
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :param only_first: import only first encountered bridge (ignored in all cases except
            WL container paths)
        :return: tuple of WildlandResult, imported WLBridge (if import was successful
        """
        raise NotImplementedError

    def bridge_import_from_data(self, yaml_data: str, paths: List[str],
                                object_owner: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Import bridge from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :return: tuple of WildlandResult, imported WLUser (if import was successful
        """
        raise NotImplementedError

    def bridge_modify(self, bridge_id: str, manifest_field: str, operation: ModifyMethod,
                      modify_data: List[str]) -> WildlandResult:
        """
        Modify bridge manifest
        :param bridge_id: id of the bridge to be modified, in the form of user_id:/.uuid/bridge_uuid
        :param manifest_field: field to modify; supports the following:
            - paths
        :param operation: operation to perform on field ('add' or 'delete')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """
        raise NotImplementedError

    def bridge_publish(self, bridge_id) -> WildlandResult:
        """
        Publish the given bridge.
        :param bridge_id: id of the bridge to be published (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError

    def bridge_unpublish(self, bridge_id) -> WildlandResult:
        """
        Unpublish the given bridge.
        :param bridge_id: id of the bridge to be unpublished (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError

    # STORAGES

    def supported_storage_backends(self) -> Tuple[WildlandResult, List[WLStorageBackend]]:
        """
        List all supported storage backends.
        :return: WildlandResult and a list of supported storage backends.
        """
        raise NotImplementedError

    def storage_create(self, backend_type: str, backend_params: Dict[str, str],
                       container_id: str, trusted: bool = False,
                       watcher_interval: Optional[int] = 0,
                       access_users: Optional[list[str]] = None, encrypt_manifest: bool = True) -> \
            Tuple[WildlandResult, Optional[WLStorage]]:
        """
        Create a storage.
        :param backend_type: storage type
        :param backend_params: params for the given backend as a dict of param_name, param_value.
        They must conform to parameter names as provided by supported_storage_backends
        :param container_id: container this storage is for
        :param trusted: should the storage be trusted
        :param watcher_interval: set the storage watcher-interval in seconds
        :param access_users: limit access to this storage to the users provided here as either
        user fingerprints or WL paths to users.
        Default: same as the container
        :param encrypt_manifest: should the storage manifest be encrypted. If this is False,
        access_users should be None. The container manifest itself might also be encrypted or not,
        this does not change its settings.
        :return: Tuple of WildlandResult and, if creation was successful, WLStorage that was
        created
        """
        raise NotImplementedError

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

    # TEMPLATES

    def template_create(self, name: str) -> Tuple[WildlandResult, Optional[WLTemplateFile]]:
        """
        Create a new empty template file under the provided name.
        :param name: name of the template to be created
        :return: Tuple of WildlandResult and, if creation was successful, WLTemplateFile that was
        created
        """
        raise NotImplementedError

    def template_add_storage(self, backend_type: str, backend_params: Dict[str, str],
                             template_name: str, read_only: bool = False,
                             default_cache: bool = False, watcher_interval: Optional[int] = 0,
                             access_users: Optional[list[str]] = None,
                             encrypt_manifest: bool = True) -> \
            Tuple[WildlandResult, Optional[WLTemplateFile]]:
        """
        Add a storage template to a template file.
        :param backend_type: storage type
        :param backend_params: params for the given backend as a dict of param_name, param_value.
        They must conform to parameter names as provided by supported_storage_backends
        :param template_name: name of an existing template file to use
        :param read_only: should the storage be read-only
        :param default_cache: mark template as default for container caches
        :param watcher_interval: set the storage watcher-interval in seconds
        :param access_users: limit access to this storage to the users provided here as a list of
        either user fingerprints or WL paths.
        Default: same as the container
        :param encrypt_manifest: should the storage manifest be encrypted. If this is False,
        access_users should be None. The container manifest itself might be encrypted, this does
        not change its settings.
        :return: Tuple of WildlandResult and, if adding was successful, WLTemplate that was
        modified
        """
        raise NotImplementedError

    def template_list(self) -> Tuple[WildlandResult, List[WLTemplateFile]]:
        """
        List all known templates.
        :return: WildlandResult, List of WLTemplateFiles
        """
        raise NotImplementedError

    def template_delete(self, template_name: str) -> WildlandResult:
        """
        Delete a template
        :param template_name: name of template to be deleted.
        """
        raise NotImplementedError

    def template_export(self, template_name: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Return (if possible) contents of the provided template
        :param template_name: name of the template
        """
        raise NotImplementedError

    def template_import(self, template_name: str, template_data: str) -> WildlandResult:
        """
        Import template from provided data.
        :param template_name: Name to be used for the template. If it exists, the contents
        will be replaced
        :param template_data: jinja template data
        """
        raise NotImplementedError

    # FORESTS

    def forest_create(self, storage_template: str, user_id: str,
                      access_users: Optional[List[str]] = None, encrypt: bool = True,
                      manifests_local_dir: Optional[str] = '/.manifests') -> WildlandResult:
        """
        Bootstrap a new forest
        :param storage_template: name of the template to be used for forest creation; must contain
        at least one writeable storage
        :param user_id: fingerprint of the user for whom the forest will be created
        :param access_users: list of additional users to the container to; provided as a list of
        either user fingerprints or WL paths to users
        :param encrypt: if the container should be encrypted; mutually exclusive with
        access_users
        :param manifests_local_dir: manifests local directory. Must be an absolute path
        :return: WildlandResult
        """
        raise NotImplementedError

    # MOUNTING

    def mount(self, paths_or_names: List[str], include_children: bool = True,
              include_parents: bool = True, remount: bool = True,
              import_users: bool = True, manifests_catalog: bool = False,
              callback: Callable[[WLContainer], None] = None) -> \
            Tuple[WildlandResult, List[WLContainer]]:
        """
        Mount containers given by name or path to their manifests or WL path to containers to
        be mounted.
        :param paths_or_names: list of container names, urls or WL urls to be mounted
        :param include_children: mount subcontainers/children of the containers found
        :param include_parents: mount main containers/parent containers even if
        subcontainers/children are found
        :param remount: remount already mounted containers, if found
        :param import_users: import users encountered on the WL path
        :param manifests_catalog: allow manifest catalogs themselves
        :param callback: a function that takes WLContainer and will be called before each container
        mount
        :return: Tuple of WildlandResult, List of successfully mounted containers; WildlandResult
        contains the list of containers that were not mounted for various reasons (from errors to
        being already mounted)
        """
        raise NotImplementedError

    def unmount_all(self) -> WildlandResult:
        """
        Unmount all mounted containers.
        """
        raise NotImplementedError

    def unmount_by_mount_path(self, paths: List[str], include_children: bool = True) -> \
            WildlandResult:
        """
        Unmount mounted containers by mount paths
        :param paths: list of mount paths to unmount
        :param include_children: should subcontainers/children be unmounted (default: true)
        :return: WildlandResult
        """
        raise NotImplementedError

    def unmount_by_path_or_name(self, path_or_name: List[str], include_children: bool = True) -> \
            WildlandResult:
        """
        Unmount containers given by name or path to their manifests or WL path to containers to
        be mounted.
        :param path_or_name:
        :type path_or_name:
        :param include_children: should subcontainers/children be unmounted (default: true)
        :return: WildlandResult
        """
        raise NotImplementedError

    def mount_status(self) -> Tuple[WildlandResult, List[WLContainer]]:
        """
        List all mounted containers
        :return: tuple of WildlandResult and mounted WLContainers
        """
        raise NotImplementedError
