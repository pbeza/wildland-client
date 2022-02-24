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

"""
Manage bridges
"""

from pathlib import Path, PurePosixPath
from typing import List, Dict, Any

import os
import click

from wildland.wildland_object.wildland_object import WildlandObject
from ..container import Container
from ..storage import StorageBackend
from ..storage_backends.file_children import FileChildrenMixin
from ..user import User
from ..utils import YAMLParserError
from ..publish import Publisher
from ..manifest.template import TemplateManager, StorageTemplate
from .cli_base import aliased_group, ContextObj
from .cli_exc import CliError
from ..wlpath import WildlandPath
from .cli_common import modify_manifest, add_fields
from .cli_container import _mount as mount_container
from .cli_container import _unmount as unmount_container
from .cli_user import refresh_users
from ..exc import WildlandError


@aliased_group('forest', short_help='Wildland Forest management')
def forest_():
    """
    Manage Wildland Forests
    """


@forest_.command(short_help='Mount Wildland Forest')
@click.argument('forest_names', nargs=-1, required=True)
@click.option('--save', '-s', is_flag=True,
              help='Save the forest containers to be mounted at startup')
@click.option('--with-cache', '-c', is_flag=True, default=False,
              help='Use the default cache storage template to create and use a new cache storage '
                   '(becomes primary storage for the container while mounted, synced with '
                   'the old primary). '
                   'Cache template to use can be overriden using the --cache-template option.')
@click.option('--cache-template', metavar='TEMPLATE',
              help='Use specified storage template to create and use a new cache storage')
@click.option('--list-all', '-l', is_flag=True,
              help='During mount, list all forest containers, including those '
                   'who did not need to be changed')
@click.option('--no-refresh-users', '-n', is_flag=True, default=False,
              help="Do not refresh remote users when mounting")
@click.pass_context
def mount(ctx: click.Context, forest_names, save: bool,
          with_cache: bool, cache_template: str,
          list_all: bool, no_refresh_users: bool):
    """
    Mount a forest given by name or path to manifest. Repeat the argument to
    mount multiple forests.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    obj: ContextObj = ctx.obj

    forests = []
    for forest_name in forest_names:
        if forest_name.endswith('*:') or not forest_name.endswith(':'):
            raise WildlandError(
                f'Failed to parse forest name: {forest_name}. '
                f'For example, ":/forests/User:" is a valid forest name')
        forests.append(f'{forest_name}*:')

    if with_cache and not cache_template:
        cache_template = obj.client.config.get('default-cache-template')
        if not cache_template:
            raise WildlandError('Default cache template not set, set one with '
                                '`wl set-default-cache` or use --cache-template option')

    # TODO: in versions v.0.0.2 or up
    # Refresh all local users; this could be optimized by refactoring search.py itself
    # to only use remote users, not local
    if not no_refresh_users:
        refresh_users(obj)

    mount_container(obj, forests, save=save, cache_template=cache_template, list_all=list_all)


@forest_.command(short_help='Unmount Wildland Forest', alias=['umount'])
@click.option('--path', metavar='PATH', help='mount path to search for')
@click.argument('forest_names', nargs=-1, required=True)
@click.pass_context
def unmount(ctx: click.Context, path: str, forest_names):
    """
    Unmount a forest given by name or path to manifest. Repeat the argument to
    unmount multiple forests.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    obj: ContextObj = ctx.obj

    forests = []
    for forest_name in forest_names:
        if forest_name.endswith('*:') or not forest_name.endswith(':'):
            raise WildlandError(
                f'Failed to parse forest name: {forest_name}. '
                f'For example, ":/forests/User:" is a valid forest name')
        forests.append(f'{forest_name}*:')
    unmount_container(obj, path=path, container_names=forests)


@forest_.command(short_help='Bootstrap Wildland Forest')
@click.argument('storage_template', required=True)
@click.option('--owner', '--user', metavar='USER', required=False,
              default='@default-owner',
              help='User for signing')
@click.option('--access', metavar='USER', required=False, multiple=True,
              help='Name of users to encrypt the container with. Can be used multiple times. '
                   'If not set, the container is unencrypted.')
@click.option('--manifest-local-dir', metavar='PATH', required=False, multiple=False,
              default='/.manifests',
              help='Set manifests local directory. Must be an absolute path.')
@click.pass_context
def create(ctx: click.Context,
           storage_template: str,
           owner: str = '@default-owner',
           manifest_local_dir: str = '/.manifests/',
           access: List[str] = None):
    """
    Bootstrap a new Forest. If owner is not specified, @default-owner is used.
    You must have a private key of the owner in order to use this command.

    \b
    Arguments:
      STORAGE_TEMPLATE      storage template used to create Forest containers

    Description

    This command creates a manifest catalog entry for the Forest.
    The storage template *must* contain at least one read-write storage.

    After the container is created, the following steps take place:

    \b
      1. A link object to the container is generated
         and appended to USER's manifests catalog.
      2. USER manifest and container manifest are copied to the
         storage from Forest manifests container

    """
    access_list = []
    if access:
        for user in access:
            if WildlandPath.WLPATH_RE.match(user):
                access_list.append({"user-path": user})
            else:
                access_list.append({"user": user})

    _bootstrap_forest(ctx, owner, storage_template, manifest_local_dir, access_list)


def _bootstrap_forest(ctx: click.Context, user: str, manifest_storage_template_name: str,
                      manifest_local_dir: str = '/', access: List[Dict] = None):

    obj: ContextObj = ctx.obj

    # Load users manifests
    try:
        forest_owner = obj.client.load_object_from_name(WildlandObject.Type.USER, user)
        if user == '@default-owner':
            # retrieve owner's name from path
            user = forest_owner.paths[0].parts[-1]
    except WildlandError as we:
        raise CliError(f'User [{user}] could not be loaded. {we}') from we

    if not obj.client.session.sig.is_private_key_available(forest_owner.owner):
        raise CliError(f'Forest owner\'s [{user}] private key not found.')

    if access:
        if len(access) == 1 and access[0].get("user", None) == '*':
            access_list = [{'user': '*'}]
        else:
            access_list = []
            try:
                for a in access:
                    if a.get("user", None):
                        access_list.append({'user': obj.client.load_object_from_name(
                                WildlandObject.Type.USER, a["user"]).owner})
                    elif a.get("user-path", None):
                        access_list.append(
                            {'user-path': WildlandPath.get_canonical_form(a["user-path"])})
            except WildlandError as we:
                raise CliError(f'User could not be loaded. {we}') from we
    else:
        access_list = [{'user': forest_owner.owner}]

    storage_templates = _resolve_storage_templates(obj, manifest_storage_template_name)

    catalog_container = None

    try:
        catalog_container = _create_container(obj, forest_owner, [Path('/.manifests')],
                                              f'{user}-forest-catalog', access_list,
                                              storage_templates, manifest_local_dir)

        assert catalog_container.local_path is not None
        assert forest_owner.local_path is not None

        catalog_storage = obj.client.select_storage(container=catalog_container,
                                                    predicate=lambda x: x.is_writeable)

        # If a writeable catalog storage doesn't have manifest_pattern defined,
        # forcibly set manifest pattern for all storages in this container.
        # TODO: improve support for more complex forms of writeable storages and more complex
        # manifest-patterns

        catalog_backend = StorageBackend.from_params(catalog_storage.params)
        if isinstance(catalog_backend, FileChildrenMixin) and \
                not catalog_backend.params.get('manifest-pattern'):
            catalog_backend.params['manifest-pattern'] = catalog_backend.DEFAULT_MANIFEST_PATTERN

        # Additionally ensure that they are going to be stored inline and override old storages
        # completely

        old_storages = list(obj.client.all_storages(catalog_container))

        catalog_container.clear_storages()

        for storage in old_storages:
            storage.params['manifest-pattern'] = catalog_storage.params['manifest-pattern']

        obj.client.add_storage_to_container(catalog_container, old_storages, inline=True)

        obj.client.save_object(WildlandObject.Type.CONTAINER, catalog_container)

        manifests_storage = obj.client.select_storage(container=catalog_container,
                                                      predicate=lambda x: x.is_writeable)
        manifests_backend = StorageBackend.from_params(manifests_storage.params)

        # Provision manifest storage with container from manifest catalog
        _bootstrap_manifest(manifests_backend, catalog_container.local_path,
                            Path('.manifests.container.yaml'))

        for storage in obj.client.all_storages(container=catalog_container):
            link_obj: Dict[str, Any] = {'object': 'link', 'file': '/.manifests.container.yaml'}

            fields = storage.to_manifest_fields(inline=True)
            if not storage.access:
                fields['access'] = obj.client.load_pubkeys_from_field(
                    access_list, forest_owner.owner)

            link_obj['storage'] = fields
            if storage.owner != forest_owner.owner:
                link_obj['storage-owner'] = storage.owner

            modify_manifest(ctx, str(forest_owner.local_path), edit_funcs=[add_fields],
                            to_add={'manifests-catalog': [link_obj]})

        # Refresh user's manifests catalog
        obj.client.recognize_users_and_bridges()

        _bootstrap_manifest(manifests_backend, forest_owner.local_path,
                            Path('forest-owner.user.yaml'))

        # Reload forest_owner to load the manifests-catalog info
        forest_owner = obj.client.load_object_from_name(WildlandObject.Type.USER, user)
        Publisher(obj.client, forest_owner).publish(catalog_container)

    except Exception as ex:
        raise CliError(f'Could not create a Forest. {ex}') from ex
    finally:
        if catalog_container and catalog_container.local_path:
            catalog_container.local_path.unlink()


def _resolve_storage_templates(obj, template_name: str) -> List[StorageTemplate]:
    try:
        tpl_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

        return tpl_manager.get_template_file_by_name(template_name).templates
    except (WildlandError, YAMLParserError) as err:
        raise CliError(f'Could not load [{template_name}] storage template. {err}') from err


def _create_container(obj: ContextObj,
                      user: User,
                      container_paths: List[Path],
                      container_name: str,
                      access: List[dict],
                      storage_templates: List[StorageTemplate],
                      storage_local_dir: str = '') -> Container:

    container = Container(owner=user.owner, paths=[PurePosixPath(p) for p in container_paths],
                          backends=[], client=obj.client, access=access)

    obj.client.save_new_object(WildlandObject.Type.CONTAINER, container, container_name)

    result = obj.wlcore.storage_do_create_from_template(
        container, storage_templates, storage_local_dir
    )
    if not result.success:
        raise CliError(str(result))

    return container


def _bootstrap_manifest(backend: StorageBackend, manifest_path: Path, file_path: Path):
    with backend:
        with backend.create(PurePosixPath(file_path), os.O_CREAT | os.O_WRONLY) as manifest_obj:
            data = manifest_path.read_bytes()
            manifest_obj.write(data, 0)
