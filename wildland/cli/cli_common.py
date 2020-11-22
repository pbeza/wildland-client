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
Common commands (sign, edit, ...) for multiple object types
'''

import sys
from pathlib import Path

import click
import yaml

from .cli_base import ContextObj
from ..client import Client
from ..user import User
from ..container import Container
from ..storage import Storage
from ..bridge import Bridge
from ..manifest.sig import SigError
from ..manifest.manifest import (
    HEADER_SEPARATOR,
    Manifest,
    ManifestError,
    split_header,
)

def find_manifest_file(client: Client, name, manifest_type) -> Path:
    '''
    CLI helper: load a manifest by name.
    '''

    if manifest_type in ['user', 'container', 'storage', 'bridge']:
        search_func = {
            'user': lambda: client.find_user_manifest(name),
            'container': lambda: client.find_local_manifest(client.container_dir, 'container',
                                                            name),
            'storage': lambda: client.find_local_manifest(client.storage_dir, 'storage', name),
            'bridge': lambda: client.find_local_manifest(client.bridge_dir, 'bridge', name),
        }[manifest_type]

        try:
            return search_func()
        except ManifestError as e:
            raise click.ClickException(f'{e}')

    raise click.ClickException(f'Not found: {name}')


def validate_manifest(manifest: Manifest, manifest_type):
    '''
    CLI helper: validate a manifest.
    '''

    if manifest_type == 'user':
        manifest.apply_schema(User.SCHEMA)
    if manifest_type == 'container':
        manifest.apply_schema(Container.SCHEMA)
    if manifest_type == 'storage':
        manifest.apply_schema(Storage.BASE_SCHEMA)
    if manifest_type == 'bridge':
        manifest.apply_schema(Bridge.SCHEMA)


@click.command(short_help='manifest signing tool')
@click.option('-o', 'output_file', metavar='FILE',
    help='output file (default is stdout)')
@click.option('-i', 'in_place', is_flag=True,
    help='modify the file in place')
@click.argument('input_file', metavar='FILE', required=False)
@click.pass_context
def sign(ctx, input_file, output_file, in_place):
    '''
    Sign a manifest given by FILE, or stdin if not given. The input file can be
    a manifest with or without header. The existing header will be ignored.

    If invoked with manifest type (``user sign``, etc.), the will also validate
    the manifest against schema.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    if in_place:
        if not input_file:
            raise click.ClickException('Cannot -i without a file')
        if output_file:
            raise click.ClickException('Cannot use both -i and -o')

    if input_file:
        path = find_manifest_file(obj.client, input_file, manifest_type)
        data = path.read_bytes()
    else:
        data = sys.stdin.buffer.read()

    manifest = Manifest.from_unsigned_bytes(data)
    if manifest_type:
        validate_manifest(manifest, manifest_type)

    obj.client.recognize_users()

    try:
        manifest.sign(obj.client.session.sig, only_use_primary_key=(manifest_type == 'user'))
    except SigError as e:
        raise click.ClickException(f'Error signing manifest: {e}')
    signed_data = manifest.to_bytes()

    if in_place:
        print(f'Saving: {path}')
        with open(path, 'wb') as f:
            f.write(signed_data)
    elif output_file:
        print(f'Saving: {output_file}')
        with open(output_file, 'wb') as f:
            f.write(signed_data)
    else:
        sys.stdout.buffer.write(signed_data)


@click.command(short_help='verify manifest signature')
@click.argument('input_file', metavar='FILE', required=False)
@click.pass_context
def verify(ctx, input_file):
    '''
    Verify a manifest signature given by FILE, or stdin if not given.

    If invoked with manifests type (``user verify``, etc.), the command will
    also validate the manifest against schema.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    if input_file:
        path = find_manifest_file(obj.client, input_file, manifest_type)
        data = path.read_bytes()
    else:
        data = sys.stdin.buffer.read()

    obj.client.recognize_users()
    try:
        manifest = Manifest.from_bytes(data, obj.client.session.sig,
                                       allow_only_primary_key=(manifest_type == 'user'))
        if manifest_type:
            validate_manifest(manifest, manifest_type)
    except ManifestError as e:
        raise click.ClickException(f'Error verifying manifest: {e}')
    click.echo('Manifest is valid')


@click.command(short_help='edit manifest in external tool')
@click.option('--editor', metavar='EDITOR',
    help='custom editor')
@click.option('--remount/--no-remount', '-r/-n', default=True,
    help='remount mounted container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def edit(ctx, editor, input_file, remount):
    '''
    Edit and sign a manifest in a safe way. The command will launch an editor
    and validate the edited file before signing and replacing it.

    If invoked with manifests type (``user edit``, etc.), the command will
    also validate the manifest against schema.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    path = find_manifest_file(obj.client, input_file, manifest_type)
    data = path.read_bytes()

    if HEADER_SEPARATOR in data:
        _, data = split_header(data)

    edited_s = click.edit(data.decode(), editor=editor, extension='.yaml',
                          require_save=False)
    data = edited_s.encode()

    obj.client.recognize_users()
    manifest = Manifest.from_unsigned_bytes(data)
    if manifest_type is not None:
        validate_manifest(manifest, manifest_type)
    manifest.sign(obj.client.session.sig, only_use_primary_key=(manifest_type == 'user'))
    signed_data = manifest.to_bytes()
    with open(path, 'wb') as f:
        f.write(signed_data)
    click.echo(f'Saved: {path}')

    if remount and manifest_type == 'container' and obj.fs_client.is_mounted():
        container = obj.client.load_container_from_path(path)
        if obj.fs_client.find_storage_id(container) is not None:
            click.echo('Container is mounted, remounting')

            user_paths = obj.client.get_bridge_paths_for_user(container.owner)
            storage = obj.client.select_storage(container)
            obj.fs_client.mount_container(
                container, storage, user_paths, remount=remount)


@click.group(short_help='modify the manifest')
def modify():
    '''
    Commands for modifying manifest elements.
    '''


@modify.command(short_help='add path to the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to add')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_path(ctx, input_file, path):
    '''
    Add a path to the manifest.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    manifest_path = find_manifest_file(obj.client, input_file, manifest_type)
    data = manifest_path.read_bytes()

    if HEADER_SEPARATOR in data:
        _, data = split_header(data)

    # TODO: editing the structure like this should be done in Manifest
    # ...but Manifest is designed to be immutable
    body_str = data.decode('utf-8')
    fields = yaml.safe_load(body_str)
    fields = Manifest.update_obsolete(fields)
    for p in path:
        if p not in fields['paths']:
            fields['paths'].append(p)
        else:
            click.echo(f'Path {p} is already in the manifest')
            continue

    manifest = Manifest.from_fields(fields)
    if manifest_type is not None:
        validate_manifest(manifest, manifest_type)

    manifest.sign(obj.client.session.sig, only_use_primary_key=(manifest_type == 'user'))

    signed_data = manifest.to_bytes()
    with open(manifest_path, 'wb') as f:
        f.write(signed_data)

    click.echo(f'Saved: {manifest_path}')


@modify.command(short_help='remove path from the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_path(ctx, input_file, path):
    '''
    Remove a path from the manifest.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    manifest_path = find_manifest_file(obj.client, input_file, manifest_type)
    data = manifest_path.read_bytes()

    if HEADER_SEPARATOR in data:
        _, data = split_header(data)

    # TODO: editing the structure like this should be done in Manifest
    # ...but Manifest is designed to be immutable
    body_str = data.decode('utf-8')
    fields = yaml.safe_load(body_str)
    fields = Manifest.update_obsolete(fields)
    for p in path:
        if p in fields['paths']:
            fields['paths'].remove(p)
        else:
            click.echo(f'Path {p} is not in the manifest')
            continue

    manifest = Manifest.from_fields(fields)
    if manifest_type is not None:
        validate_manifest(manifest, manifest_type)

    manifest.sign(obj.client.session.sig, only_use_primary_key=(manifest_type == 'user'))

    signed_data = manifest.to_bytes()
    with open(manifest_path, 'wb') as f:
        f.write(signed_data)

    click.echo(f'Saved: {manifest_path}')
>>>>>>> d3e157f... cli: add modify/del-path subcommand
