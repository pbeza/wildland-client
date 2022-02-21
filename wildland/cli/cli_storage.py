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

"""
Storage object
"""

import types
from typing import List, Optional, Type
import functools
import click

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import aliased_group, ContextObj
from .cli_exc import CliError
from .cli_utils import parse_storage_cli_options, param_name_from_cli
from .cli_common import sign, verify, edit, modify_manifest, set_fields, \
    add_fields, del_fields, dump, check_if_any_options, check_options_conflict, \
    publish, unpublish
from ..core.wildland_objects_api import WLStorage, WLContainer, WLObjectType
from ..log import get_logger
from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..exc import WildlandError
from ..utils import format_command_options

logger = get_logger('cli-storage')


@aliased_group('storage', short_help='storage management')
def storage_():
    """Manage storages for container"""


@storage_.group(short_help='create storage')
def create():
    """
    Create a new storage manifest.

    The storage has to be associated with a specific container.
    """


def _make_create_command(backend: Type[StorageBackend]):
    params = [
        click.Option(['--container'], metavar='CONTAINER',
                     required=True,
                     help='Container this storage is for'),
        click.Option(['--trusted'], is_flag=True,
                     help='Make the storage trusted.'),
        click.Option(['--inline/--no-inline'], default=True,
                     help='Add the storage directly to container '
                     'manifest, instead of saving it to a file.'),
        click.Option(['--watcher-interval'], metavar='SECONDS', required=False, type=int,
                     help='Set the storage watcher-interval in seconds.'),
        click.Option(['--access'], multiple=True, required=False, metavar='USER',
                     help='limit access to this storage to the provided users. '
                          'Default: same as the container.'),
        click.Option(['--encrypt-manifest/--no-encrypt-manifest'], default=True,
                     required=False,
                     help='If --no-encrypt-manifest, this manifest will not be encrypted and '
                          '--access cannot be used. For inline storage, container manifest might '
                          'still be encrypted.'),
        click.Option(['--no-publish'], is_flag=True,
                     help='do not publish the container after creation.'),
        click.Option(['--skip-sync'], is_flag=True,
                     help='Skip syncing from the first local storage to the created storage. If '
                          'the created storage is local then syncing is skipped regardless if '
                          'this option is present or not.'),
        click.Argument(['name'], metavar='NAME', required=False),
    ]
    params.extend(parse_storage_cli_options(backend.storage_options()))
    callback = functools.partial(_do_create, backend=backend)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage',
        params=params,
        callback=callback,
        context_settings={'show_default': True})
    setattr(command, "format_options", types.MethodType(format_command_options, command))
    return command


def _add_create_commands(group: click.core.Group):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        name: Optional[str],
        container: str,
        trusted: bool,
        inline: bool,
        watcher_interval: Optional[int],
        access: List[str],
        encrypt_manifest: bool,
        no_publish: bool,
        skip_sync: bool,
        **data):

    obj: ContextObj = click.get_current_context().obj

    wl_container_result, wl_container = obj.wlcore.object_get(WLObjectType.CONTAINER, container)
    if not wl_container_result.success or not wl_container:
        raise CliError(str(wl_container_result))
    container_id = wl_container.id

    data = {param_name_from_cli(key): data[key] for key in data}

    create_result, wl_storage = obj.wlcore.storage_create(
        backend.TYPE, data, container_id, name, trusted,
        watcher_interval, inline, access, encrypt_manifest
    )

    if not create_result.success or not wl_storage:
        raise CliError(f'Failed to create storage: {create_result}')
    storage_id = wl_storage.id

    remount_result = obj.wlcore.container_remount(container_id)
    if not remount_result.success:
        raise CliError(str(remount_result))

    if not no_publish:
        publish_result = obj.wlcore.container_publish(container_id)
        if not publish_result.success:
            raise CliError(str(publish_result))

    if skip_sync:
        logger.info('Skipping syncing as requested.')
        return

    sync_result = obj.wlcore.storage_sync_container(storage_id, container_id)
    if not sync_result.success:
        raise CliError(str(sync_result))


@storage_.command('list', short_help='list storages', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known storages.
    """
    storages_result, storages = obj.wlcore.storage_list()
    containers_result, containers = obj.wlcore.container_list()
    if not storages_result.success or not containers_result.success:
        raise CliError(f'{str(storages_result) + str(containers_result)}')

    __print_storages_info(storages)
    __print_containers_info(containers)


def __print_storages_info(storages: List[WLStorage]):
    for storage in storages:
        click.echo(f'  type: {storage.storage_type}')
        click.echo(f'  backend_id: {storage.backend_id}')
        if storage.storage_type in ['local', 'local-cached', 'local-dir-cached']:
            click.echo(f'  location: {storage.location}')


def __print_containers_info(containers: List[WLContainer]):
    for container in containers:
        if not container.storage_description:
            continue

        click.echo(f'container id: {container.id}')
        for description in container.storage_description:
            click.echo(description)


@storage_.command('delete', short_help='delete a storage; sync removed storage with the first '
    'remote storage (or to the first local storage if no remote storage was found)',
    alias=['rm', 'remove'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if used by containers or if manifest cannot be loaded;'
                   ' skip attempting to sync storage with remaining storage(s)')
@click.option('--no-cascade', is_flag=True,
              help='remove reference from containers')
@click.option('--container', metavar='CONTAINER',
              help='remove reference from specific containers')
@click.argument('names', metavar='NAME', nargs=-1)
def delete(obj: ContextObj, names, force: bool, no_cascade: bool, container: Optional[str]):
    """
    Delete a storage.
    """

    error_messages = ''
    for name in names:
        try:
            _delete(obj, name, force, no_cascade, container)
        except Exception as e:
            error_messages += f'{e}\n'

    if error_messages:
        raise CliError(f'Some storages could not be deleted:\n{error_messages.strip()}')


def _delete(obj: ContextObj, name: str, force: bool, no_cascade: bool, container: Optional[str]):
    cascade = not no_cascade
    if cascade:
        if __check_if_storage_in_use_and_try_to_delete(obj, name, container):
            return

    delete_result = obj.wlcore.storage_delete(name, cascade, force)

    if not delete_result.success:
        raise CliError(str(delete_result))


def __check_if_storage_in_use_and_try_to_delete(
        obj: ContextObj,
        storage_name: str,
        container_name: Optional[str]) -> bool:
    result, local_path, usages = obj.wlcore.storage_get_local_path_and_find_usages(storage_name)
    if not local_path and usages:
        if len(usages) > 1:
            if container_name is None:
                raise CliError(f'Storage {storage_name} is used '
                               f'in multiple containers: {[str(cont) for cont in usages]} '
                               '(please specify container name with --container)')

            usages = obj.wlcore.storage_get_usages_within_container(usages, container_name)
            if not result.success:
                raise CliError(str(result))

            if usages:
                if len(usages) > 1:
                    if not click.confirm('Several matching results have been found: \n'
                                         f'{usages} \n'
                                         f'Do you want remove all listed storages?'):
                        return False

                result = obj.wlcore.storage_delete_cascade(usages)
                if not result.success:
                    raise CliError(str(result))
                return True

    return False


@storage_.command('create-from-template', short_help='create a storage from a storage template',
                  alias=['cs'])
@click.option('--storage-template', '--template', '-t', multiple=False, required=True,
              help='name of storage template to use')
@click.option('--local-dir', multiple=False, required=False,
              help='local directory to be passed to storage templates')
@click.option('--no-publish', is_flag=True,
              help='do not publish the container after creation')
@click.argument('cont', metavar='CONTAINER', required=True)
@click.pass_obj
def create_from_template(obj: ContextObj, cont, storage_template: str, local_dir=None,
                         no_publish=False):
    """
    Setup storage for a container from a storage template.
    """
    container_result, wl_container = obj.wlcore.object_get(WLObjectType.CONTAINER, cont)
    if not container_result.success or not wl_container:
        raise CliError(f'Container not found: {str(container_result)}')

    container_id = wl_container.id
    result = obj.wlcore.storage_create_from_template(
        storage_template, container_id, local_dir
    )
    if not result.success:
        raise CliError(str(result))

    if not no_publish:
        publish_result = obj.wlcore.container_publish(container_id)
        if not publish_result.success:
            raise CliError(str(publish_result))


@storage_.command(short_help='modify storage manifest')
@click.option('--location', metavar='PATH', help='location to set')
@click.option('--add-access', metavar='PATH', multiple=True, help='users to add access for')
@click.option('--del-access', metavar='PATH', multiple=True, help='users to remove access for')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def modify(ctx: click.Context,
           location, add_access, del_access, input_file
           ):
    """
    Command for modifying storage manifests.
    """
    check_if_any_options(ctx, location, add_access, del_access)
    check_options_conflict("access", add_access, del_access)

    try:
        add_access_owners = [
            {'user': ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
            for user in add_access]
        del_access_owners = [
            {'user': ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
            for user in del_access]
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    to_add = {'access': add_access_owners}
    to_del = {'access': del_access_owners}
    to_set = {}
    if location:
        to_set['location'] = location
    modify_manifest(ctx, input_file,
                    edit_funcs=[add_fields, del_fields, set_fields],
                    to_add=to_add,
                    to_del=to_del,
                    to_set=to_set,
                    logger=logger)


storage_.add_command(sign)
storage_.add_command(verify)
storage_.add_command(edit)
storage_.add_command(dump)
storage_.add_command(publish)
storage_.add_command(unpublish)

_add_create_commands(create)
