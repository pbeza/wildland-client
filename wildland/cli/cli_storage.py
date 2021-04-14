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

"""
Storage object
"""

from typing import Type, List
from pathlib import Path, PurePosixPath
import functools
import uuid
import copy

import click
import uritools

from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit, modify_manifest, set_field, add_field, del_field, dump
from ..storage import Storage
from ..manifest.template import TemplateManager

from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..manifest.manifest import ManifestError, WildlandObjectType
from ..exc import WildlandError


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
                     help='Make the storage trusted. Default: false'),
        click.Option(['--inline/--no-inline'], default=True,
                     help='Add the storage directly to container '
                     'manifest, instead of saving it to a file. Default: inline.'),
        click.Option(['--manifest-pattern'], metavar='GLOB',
                     help='Set the manifest pattern for storage'),
        click.Option(['--watcher-interval'], metavar='SECONDS', required=False,
                     help='Set the storage watcher-interval in seconds.'),
        click.Option(['--base-url'], metavar='BASEURL',
                     help='Set public base URL'),
        click.Option(['--access'], multiple=True, required=False, metavar='USER',
                     help="limit access to this storage to the provided users. "
                          "Default: same as the container."),
        click.Argument(['name'], metavar='NAME', required=False),
    ]

    params.extend(backend.cli_options())

    callback = functools.partial(_do_create, backend=backend)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage',
        params=params,
        callback=callback)
    return command


def _add_create_commands(group):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        name,
        container,
        trusted,
        manifest_pattern,
        inline,
        watcher_interval,
        base_url,
        access,
        **data):

    obj: ContextObj = click.get_current_context().obj

    obj.client.recognize_users()

    container = obj.client.load_object_from_name(WildlandObjectType.CONTAINER, container)
    if not container.local_path:
        raise WildlandError('Need a local container')

    container_mount_path = container.paths[0]
    click.echo(f'Using container: {container.local_path} ({container_mount_path})')

    params = backend.cli_create(data)

    # remove default, non-required values
    for param, value in list(params.items()):
        if value is None or value == []:
            del params[param]

    if watcher_interval:
        params['watcher-interval'] = int(watcher_interval)

    params['backend-id'] = str(uuid.uuid4())
    if base_url is not None:
        params['base-url'] = base_url

    manifest_pattern_dict = None
    if manifest_pattern:
        manifest_pattern_dict = {
            'type': 'glob',
            'path': manifest_pattern,
        }

    if access:
        access = [{'user': obj.client.load_object_from_name(
            WildlandObjectType.USER, user).owner} for user in access]
    else:
        if container.access:
            access = container.access
        else:
            access = None

    storage = Storage(
        storage_type=backend.TYPE,
        owner=container.owner,
        container_path=container_mount_path,
        params=params,
        trusted=params.get('trusted', trusted),
        manifest_pattern=params.get('manifest_pattern', manifest_pattern_dict),
        access=access
    )
    storage.validate()
    click.echo(f'Adding storage {storage.backend_id} to container.')
    obj.client.add_storage_to_container(container, storage, inline, name)
    click.echo(f'Saved container {container.local_path}')


@storage_.command('list', short_help='list storages', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known storages.
    """

    obj.client.recognize_users()

    for storage in obj.client.load_all(WildlandObjectType.STORAGE):
        click.echo(storage.local_path)
        click.echo(f'  type: {storage.storage_type}')
        if 'backend_id' in storage.params:
            click.echo(f'  backend_id: {storage.params["backend_id"]}')
        if storage.storage_type in ['local', 'local-cached', 'local-dir-cached']:
            click.echo(f'  location: {storage.params["location"]}')

    for container in obj.client.load_all(WildlandObjectType.CONTAINER):
        backends = []
        for backend in container.backends:
            if not isinstance(backend, str):
                backends.append(backend)
        if not backends:
            continue

        click.echo(f'{container.local_path} (inline)')
        for backend in backends:
            click.echo(f'  - type: {backend["type"]}')
            if 'backend_id' in backend:
                click.echo(f'    backend_id: {backend["backend_id"]}')
            if backend['type'] in ['local', 'local-cached', 'local-dir-cached']:
                click.echo(f'    location: {backend["location"]}')


@storage_.command('delete', short_help='delete a storage', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if used by containers or if manifest cannot be loaded')
@click.option('--cascade', is_flag=True,
              help='remove reference from containers')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade):
    """
    Delete a storage.
    """

    obj.client.recognize_users()

    try:
        storage = obj.client.load_object_from_name(WildlandObjectType.STORAGE, name)
    except ManifestError as ex:
        if force:
            click.echo(f'Failed to load manifest: {ex}')
            try:
                path = obj.client.find_local_manifest(WildlandObjectType.STORAGE, name)
                if path:
                    click.echo(f'Deleting file {path}')
                    path.unlink()
            except ManifestError:
                # already removed
                pass
            if cascade:
                click.echo('Unable to cascade remove: manifest failed to load.')
            return
        click.echo(f'Failed to load manifest, cannot delete: {ex}')
        click.echo('Use --force to force deletion.')
        return

    if not storage.local_path:
        raise WildlandError('Can only delete a local manifest')

    used_by = []
    for container in obj.client.load_all(WildlandObjectType.CONTAINER):
        assert container.local_path
        modified = False
        for url_or_dict in list(container.backends):
            if (isinstance(url_or_dict, str) and
                obj.client.parse_file_url(url_or_dict, container.owner) == storage.local_path):

                if cascade:
                    click.echo('Removing {} from {}'.format(
                        url_or_dict, container.local_path))
                    container.backends.remove(url_or_dict)
                    modified = True
                else:
                    click.echo('Storage used in container: {}'.format(
                        container.local_path))
                    used_by.append(container)
        if modified:
            click.echo(f'Saving: {container.local_path}')
            obj.client.save_object(WildlandObjectType.CONTAINER, container)

    if used_by and not force:
        raise CliError('Storage is still used, not deleting '
                       '(use --force or --cascade)')

    click.echo(f'Deleting: {storage.local_path}')
    storage.local_path.unlink()


def do_create_storage_from_set(client, container, storage_set, local_dir):
    """
    Create storages for a container from a given StorageSet.
    :param client: Wildland client
    :param container: Wildland container
    :param storage_set: StorageSet of manifest templates
    :param local_dir: str to be passed to template renderer as a parameter, can be used by template
        creators
    """
    if isinstance(storage_set, str):
        template_manager = TemplateManager(client.dirs[WildlandObjectType.SET])
        storage_set = template_manager.get_storage_set(storage_set)

    for file, t in storage_set.templates:
        try:
            manifest = file.get_unsigned_manifest(container, local_dir)
        except ValueError as ex:
            click.echo(f'Failed to create manifest in template {file.file_name}: {ex}')
            raise ex

        manifest.encrypt_and_sign(client.session.sig, encrypt=False)

        storage = Storage.from_manifest(manifest,
                                        local_owners=client.config.get('local-owners'))
        backend = StorageBackend.from_params(storage.params)

        if storage.is_writeable and backend.LOCATION_PARAM:
            path = storage.params[backend.LOCATION_PARAM]

            is_uri = uritools.isuri(path)

            if is_uri:
                uri      = uritools.urisplit(path)
                rel_path = uri.path
            else:
                rel_path = path

            path_chunks          = list(PurePosixPath(rel_path).parts)
            to_create: List[str] = []

            while path_chunks:
                path_chunks_str = str(Path.joinpath(*[Path(p) for p in path_chunks]))

                if is_uri:
                    uri_path = path_chunks_str
                    rel_path = uritools.uricompose(scheme=uri.scheme, host=uri.host, port=uri.port,
                                                   query=uri.query, fragment=uri.fragment,
                                                   path=uri_path)
                else:
                    rel_path = path_chunks_str

                try_storage = copy.deepcopy(storage)
                try_storage.params[backend.LOCATION_PARAM] = rel_path

                try_backend = StorageBackend.from_params(try_storage.params)

                try:
                    try_backend.mount()
                    try_backend.getattr(PurePosixPath(''))

                    for idx, _ in enumerate(to_create):
                        next_dir = Path.joinpath(*[Path(p) for p in to_create[:idx+1]])
                        try_backend.mkdir(PurePosixPath(next_dir))

                    try_backend.unmount()
                    break
                except Exception:
                    try_backend.unmount()
                    to_create.insert(0, path_chunks.pop())

        click.echo(f'Adding storage {storage.backend_id} to container.')
        client.add_storage_to_container(container=container, storage=storage,
                                        inline=(t == 'inline'), storage_name=storage_set.name)
        click.echo(f'Saved container {container.local_path}')


@storage_.command('create-from-set', short_help='create a storage from a set of templates',
                  alias=['cs'])
@click.option('--storage-set', '--set', '-s', multiple=False, required=False,
              help='name of storage template set to use')
@click.option('--local-dir', multiple=False, required=False,
              help='local directory to be passed to storage templates')
@click.argument('cont', metavar='CONTAINER', required=True)
@click.pass_obj
def create_from_set(obj: ContextObj, cont, storage_set=None, local_dir=None):
    """
    Setup storage for a container from a storage template set.
    """

    obj.client.recognize_users()
    container = obj.client.load_object_from_name(WildlandObjectType.CONTAINER, cont)
    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])

    if not storage_set:
        storage_set = obj.client.config.get('default-storage-set-for-user')\
            .get(container.owner, None)
        if not storage_set:
            raise WildlandError(f'User {container.owner} has no default storage template set. '
                                f'Specify template set explicitly.')

    try:
        storage_set = template_manager.get_storage_set(storage_set)
    except FileNotFoundError as fnf:
        raise WildlandError(f'Storage set {storage_set} not found.') from fnf

    try:
        do_create_storage_from_set(obj.client, container, storage_set, local_dir)
    except ValueError:
        pass


storage_.add_command(sign)
storage_.add_command(verify)
storage_.add_command(edit)
storage_.add_command(dump)

_add_create_commands(create)


@storage_.group(short_help='modify storage manifest')
def modify():
    """
    Commands for modifying storage manifests.
    """


@modify.command(short_help='set location in the manifest')
@click.argument('input_file', metavar='FILE')
@click.option('--location', metavar='PATH', required=True, help='Location to set')
@click.pass_context
def set_location(ctx: click.Context, input_file, location):
    """
    Set location in the manifest.
    """
    modify_manifest(ctx, input_file, set_field, 'location', location)


@modify.command(short_help='allow additional user(s) access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users to add access for')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_access(ctx: click.Context, input_file, access):
    """
    Add category to the manifest.
    """
    ctx.obj.client.recognize_users()

    processed_access = []

    try:
        for user in access:
            user = ctx.obj.client.load_object_from_name(WildlandObjectType.USER, user)
            processed_access.append({'user': user.owner})
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    modify_manifest(ctx, input_file, add_field, 'access', processed_access)


@modify.command(short_help='stop additional user(s) from having access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users whose access should be revoked')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_access(ctx: click.Context, input_file, access):
    """
    Remove category from the manifest.
    """
    ctx.obj.client.recognize_users()

    processed_access = []

    try:
        for user in access:
            user = ctx.obj.client.load_object_from_name(WildlandObjectType.USER, user)
            processed_access.append({'user': user.owner})
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    modify_manifest(ctx, input_file, del_field, 'access', processed_access)
