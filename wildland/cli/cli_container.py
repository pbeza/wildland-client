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
Manage containers
'''

from pathlib import PurePosixPath, Path
from typing import List, Tuple, Dict, Optional
import os
import traceback

import click

from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit
from ..container import Container
from ..storage import Storage
from ..client import Client
from ..fs_client import WildlandFSClient, WatchEvent


@aliased_group('container', short_help='container management')
def container_():
    '''
    Manage containers
    '''


class OptionRequires(click.Option):
    """
    Helper class to provide conditional required for click.Option
    """
    def __init__(self, *args, **kwargs):
        try:
            self.required_opt = kwargs.pop('requires')
        except KeyError:
            raise click.UsageError("'requires' parameter must be present")
        kwargs['help'] = kwargs.get('help', '') + \
            ' NOTE: this argument requires {}'.format(self.required_opt)
        super(OptionRequires, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        if self.name in opts and self.required_opt not in opts:
            raise click.UsageError("option --{} requires --{}".format(
                self.name, self.required_opt))
        # noinspection Mypy
        self.prompt = None
        return super(OptionRequires, self).handle_parse_result(ctx, opts, args)


@container_.command(short_help='create container')
@click.option('--user',
    help='user for signing')
@click.option('--path', multiple=True, required=True,
    help='mount path (can be repeated)')
@click.option('--category', multiple=True, required=False,
    help='category, will be used to generate mount paths')
@click.option('--title', multiple=False, required=False,
    help='container title')
@click.option('--update-user/--no-update-user', '-u/-n', default=False,
              help='Attach the container to the user')
@click.argument('name', metavar='CONTAINER', required=False)
@click.pass_obj
def create(obj: ContextObj, user, path, name, update_user, title=None, category=None):
    '''
    Create a new container manifest.
    '''

    obj.client.recognize_users()
    user = obj.client.load_user_from(user or '@default-signer')

    if category and not title:
        if not name:
            raise CliError('--category option requires --title or container name')
        title = name

    container = Container(
        signer=user.signer,
        paths=[PurePosixPath(p) for p in path],
        backends=[],
        title=title,
        categories=category
    )

    path = obj.client.save_new_container(container, name)
    click.echo(f'Created: {path}')

    if update_user:
        if not user.local_path:
            raise CliError('Cannot update user because the manifest path is unknown')
        click.echo('Attaching container to user')

        user.containers.append(str(obj.client.local_url(path)))
        obj.client.save_user(user)


@container_.command(short_help='update container')
@click.option('--storage', multiple=True,
    help='storage to use (can be repeated)')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def update(obj: ContextObj, storage, cont):
    '''
    Update a container manifest.
    '''

    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)
    if container.local_path is None:
        raise click.ClickException('Can only update a local manifest')

    if not storage:
        print('No change')
        return

    for storage_name in storage:
        storage = obj.client.load_storage_from(storage_name)
        assert storage.local_path
        print(f'Adding storage: {storage.local_path}')
        if str(storage.local_path) in container.backends:
            raise click.ClickException('Storage already attached to container')
        container.backends.append(obj.client.local_url(storage.local_path))

    obj.client.save_container(container)


@container_.command('list', short_help='list containers', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known containers.
    '''

    obj.client.recognize_users()
    for container in obj.client.load_containers():
        click.echo(container.local_path)
        click.echo(f'  signer: {container.signer}')
        for container_path in container.expanded_paths:
            click.echo(f'  path: {container_path}')
        for storage_path in container.backends:
            click.echo(f'  storage: {storage_path}')
        click.echo()

@container_.command('delete', short_help='delete a container', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even when using local storage manifests')
@click.option('--cascade', is_flag=True,
              help='also delete local storage manifests')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade):
    '''
    Delete a container.
    '''
    # TODO: also consider detecting user-container link (i.e. user's main
    # container).
    obj.client.recognize_users()

    container = obj.client.load_container_from(name)
    if not container.local_path:
        raise CliError('Can only delete a local manifest')

    has_local = False
    for url_or_dict in list(container.backends):
        if isinstance(url_or_dict, str):
            path = obj.client.parse_file_url(url_or_dict, container.signer)
            if path and path.exists():
                if cascade:
                    click.echo('Deleting storage: {}'.format(path))
                    path.unlink()
                else:
                    click.echo('Container refers to a local manifest: {}'.format(path))
                    has_local = True

    if has_local and not force:
        raise CliError('Container refers to local manifests, not deleting '
                       '(use --force or --cascade)')

    click.echo(f'Deleting: {container.local_path}')
    container.local_path.unlink()


container_.add_command(sign)
container_.add_command(verify)
container_.add_command(edit)


@container_.command(short_help='mount container')
@click.option('--remount/--no-remount', '-r/-n', default=True,
              help='Remount existing container, if found')
@click.option('--save', '-s', is_flag=True,
              help='Save the container to be mounted at startup')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount(obj: ContextObj, container_names, remount, save):
    '''
    Mount a container given by name or path to manifest. Repeat the argument to
    mount multiple containers.

    The Wildland system has to be mounted first, see ``wl mount``.
    '''
    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()

    params: List[Tuple[Container, Storage, bool]] = []
    for container_name in container_names:
        for container in obj.client.load_containers_from(container_name):
            is_default_user = container.signer == obj.client.config.get('@default')
            storage = obj.client.select_storage(container)
            param_tuple = (container, storage, is_default_user)

            if obj.fs_client.find_storage_id(container) is None:
                print(f'new: {container.local_path}')
                params.append(param_tuple)
            elif remount:
                if obj.fs_client.should_remount(container, storage, is_default_user):
                    print(f'changed: {container.local_path}')
                    params.append(param_tuple)
                else:
                    print(f'not changed: {container.local_path}')
            else:
                raise CliError('Already mounted: {container.local_path}')

    if len(params) > 1:
        click.echo(f'Mounting {len(params)} containers')
        obj.fs_client.mount_multiple_containers(params, remount=remount)
    elif len(params) > 0:
        click.echo('Mounting 1 container')
        obj.fs_client.mount_multiple_containers(params, remount=remount)
    else:
        click.echo('No containers need remounting')

    if save:
        default_containers = obj.client.config.get('default-containers')
        default_containers_set = set(default_containers)
        new_default_containers = default_containers.copy()
        for container_name in container_names:
            if container_name in default_containers_set:
                click.echo(f'Already in default-containers: {container_name}')
                continue
            click.echo(f'Adding to default-containers: {container_name}')
            default_containers_set.add(container_name)
            new_default_containers.append(container_name)
        if len(new_default_containers) > len(default_containers):
            obj.client.config.update_and_save(
                {'default-containers': new_default_containers})


@container_.command(short_help='unmount container', alias=['umount'])
@click.option('--path', metavar='PATH',
    help='mount path to search for')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=False)
@click.pass_obj
def unmount(obj: ContextObj, path: str, container_names):
    '''
    Unmount a container_ You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    '''

    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()

    if bool(container_names) + bool(path) != 1:
        raise click.UsageError('Specify either container or --path')

    if container_names:
        storage_ids = []
        for container_name in container_names:
            for container in obj.client.load_containers_from(container_name):
                storage_id = obj.fs_client.find_storage_id(container)
                if storage_id is None:
                    click.echo(f'Not mounted: {container.paths[0]}')
                else:
                    click.echo(f'Will unmount: {container.paths[0]}')
                    storage_ids.append(storage_id)
    else:
        storage_id = obj.fs_client.find_storage_id_by_path(PurePosixPath(path))
        if storage_id is None:
            raise click.ClickException('Container not mounted')
        storage_ids = [storage_id]

    if not storage_ids:
        raise click.ClickException('No containers mounted')

    click.echo(f'Unmounting {len(storage_ids)} containers')
    for storage_id in storage_ids:
        obj.fs_client.unmount_container(storage_id)


class Remounter:
    '''
    A class for watching files and remounting if necessary.
    '''

    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 container_names: List[str]):
        self.client = client
        self.fs_client = fs_client

        self.patterns: List[str] = []
        for name in container_names:
            path = Path(os.path.expanduser(name)).resolve()
            relpath = path.relative_to(self.fs_client.mount_dir)
            self.patterns.append(str(PurePosixPath('/') / relpath))

        # Queued operations
        self.to_mount: List[Tuple[Container, Storage, bool]] = []
        self.to_unmount: List[int] = []

        # manifest path -> main container path
        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

    def run(self):
        '''
        Run the main loop.
        '''

        click.echo(f'Using patterns: {self.patterns}')
        for events in self.fs_client.watch(self.patterns, with_initial=True):
            click.echo()
            for event in events:
                try:
                    self.handle_event(event)
                except Exception:
                    click.echo('error in handle_event')
                    traceback.print_exc()

            self.unmount_pending()
            self.mount_pending()

    def handle_event(self, event: WatchEvent):
        '''
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        '''

        click.echo(f'{event.event_type}: {event.path}')

        # Find out if we've already seen the file, and can match it to a
        # mounted storage.
        storage_id: Optional[int] = None
        if event.path in self.main_paths:
            storage_id = self.fs_client.find_storage_id_by_path(
                self.main_paths[event.path])

        # Handle delete: unmount if the file was mounted.
        if event.event_type == 'delete':
            # Stop tracking the file
            if event.path in self.main_paths:
                del self.main_paths[event.path]

            if storage_id is not None:
                click.echo(f'  (unmount {storage_id})')
                self.to_unmount.append(storage_id)
            else:
                click.echo('  (not mounted)')

        # Handle create/modify:
        if event.event_type in ['create', 'modify']:
            local_path = self.fs_client.mount_dir / event.path.relative_to('/')
            container = self.client.load_container_from_path(local_path)

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_path(
                container.signer, container.paths[0])

            # Check if the container is NOT detected as currently mounted under
            # this path. This might happen if the modified file changes UUID.
            # In this case, we want to unmount the old one.
            current_storage_id = self.fs_client.find_storage_id(container)
            if storage_id is not None and storage_id != current_storage_id:
                click.echo(f'  (unmount old: {storage_id})')

            # Call should_remount to determine if we should mount this
            # container.
            is_default_user = container.signer == self.client.config.get('@default')
            storage = self.client.select_storage(container)
            if self.fs_client.should_remount(container, storage, is_default_user):
                click.echo('  (mount)')
                self.to_mount.append((container, storage, is_default_user))
            else:
                click.echo('  (no change)')

    def unmount_pending(self):
        '''
        Unmount queued containers.
        '''

        for storage_id in self.to_unmount:
            self.fs_client.unmount_container(storage_id)
        self.to_unmount.clear()

    def mount_pending(self):
        '''
        Mount queued containers.
        '''

        self.fs_client.mount_multiple_containers(self.to_mount, remount=True)
        self.to_mount.clear()


@container_.command('mount-watch', short_help='mount container')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount_watch(obj: ContextObj, container_names):
    '''
    Watch for manifest files inside Wildland, and keep the filesystem mount
    state in sync.
    '''

    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()

    remounter = Remounter(obj.client, obj.fs_client, container_names)
    remounter.run()
