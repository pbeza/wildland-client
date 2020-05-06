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
Wildland command-line interface.
'''

import os
from pathlib import Path
import json

import click

from .cli_base import CliError, ContextObj
from . import (
    cli_common,
    cli_user,
    cli_storage,
    cli_container,
    cli_transfer
)

from ..container import Container
from ..log import init_logging
from ..manifest.loader import ManifestLoader
from .. import __version__ as _version



PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'

@click.group()
@click.option('--dummy/--no-dummy', default=False,
    help='use dummy signatures')
@click.option('--base-dir', default=None,
    help='base directory for configuration')
@click.option('--verbose', '-v', count=True,
              help='output logs (repeat for more verbosity)')
@click.version_option(_version)
@click.pass_context
def main(ctx, base_dir, dummy, verbose):
    # pylint: disable=missing-docstring
    ctx.obj = ContextObj(ManifestLoader(dummy=dummy, base_dir=base_dir))
    if verbose > 0:
        init_logging(level='DEBUG' if verbose > 1 else 'INFO')


main.add_command(cli_user.user)
main.add_command(cli_storage.storage)
main.add_command(cli_container.container_)

main.add_command(cli_common.sign)
main.add_command(cli_common.verify)
main.add_command(cli_common.edit)

main.add_command(cli_transfer.get)
main.add_command(cli_transfer.put)


def _do_mount_containers(to_mount):
    '''
    Issue a series of .control/mount commands.
    '''
    ctx = click.get_current_context()

    for path, command in to_mount:
        print(f'Mounting: {path}')
        try:
            with open(ctx.obj.mount_dir / '.control/mount', 'wb') as f:
                f.write(json.dumps(command).encode())
        except IOError as e:
            ctx.obj.unmount()
            raise click.ClickException(f'Failed to mount {path}: {e}')


@main.command(short_help='mount Wildland filesystem')
@click.option('--remount', '-r', is_flag=True,
    help='if mounted already, remount')
@click.option('--debug', '-d', count=True,
    help='debug mode: run in foreground (repeat for more verbosity)')
@click.option('--container', '-c', metavar='CONTAINER', multiple=True,
    help='Container to mount (can be repeated)')
@click.pass_obj
def mount(obj: ContextObj, remount, debug, container):
    '''
    Mount the Wildland filesystem. The default path is ``~/wildland/``, but
    it can be customized in the configuration file
    (``~/.widland/config.yaml``) as ``mount_dir``.
    '''

    if not os.path.exists(obj.mount_dir):
        print(f'Creating: {obj.mount_dir}')
        os.makedirs(obj.mount_dir)

    if obj.client.is_mounted():
        if remount:
            obj.client.unmount()
        else:
            raise CliError(f'Already mounted')

    obj.loader.load_users()
    to_mount = []
    if container:
        for name in container:
            path, manifest = obj.loader.load_manifest(name, 'container')
            if not manifest:
                raise CliError(f'Container not found: {name}')
            container = Container(manifest)
            to_mount.append((path,
                obj.client.get_command_for_mount_container(container)))

    if not debug:
        obj.client.mount()
        _do_mount_containers(to_mount)
        return

    print(f'Mounting in foreground: {obj.mount_dir}')
    print('Press Ctrl-C to unmount')

    p = obj.client.mount(foreground=True, debug=(debug > 1))
    _do_mount_containers(to_mount)
    try:
        p.wait()
    except KeyboardInterrupt:
        obj.client.unmount()
        p.wait()

    if p.returncode != 0:
        raise CliError(f'FUSE driver exited with failure')

@main.command(short_help='unmount Wildland filesystem')
@click.pass_obj
def unmount(obj: ContextObj):
    '''
    Unmount the Wildland filesystem.
    '''

    click.echo(f'Unmounting: {obj.mount_dir}')
    obj.client.unmount()


if __name__ == '__main__':
    main() # pylint: disable=no-value-for-parameter
