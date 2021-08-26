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
Common commands (sign, edit, ...) for multiple object types
"""
import copy
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Any, Optional, Dict, Tuple

import click
import yaml

from wildland import __version__
from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import ContextObj, CliError, cli_warn
from ..client import Client
from ..container import Container
from ..manifest.sig import SigError
from ..manifest.manifest import (
    HEADER_SEPARATOR,
    Manifest,
    ManifestError,
    split_header,
)
from ..manifest.schema import SchemaError
from ..exc import WildlandError


def find_manifest_file(client: Client, name: str, manifest_type: Optional[str]) -> Path:
    """
    CLI helper: load a manifest by name.
    """
    try:
        object_type: Optional[WildlandObject.Type] = WildlandObject.Type(manifest_type)
    except ValueError:
        object_type = None

    path = client.find_local_manifest(object_type, name)
    if path:
        return path

    raise click.ClickException(f'Manifest not found: {name}')


def validate_manifest(manifest: Manifest, manifest_type, client: Client):
    """
    CLI helper: validate a manifest.
    """
    try:
        wl_type: Optional[WildlandObject.Type] = WildlandObject.Type(manifest_type)
    except ValueError:
        wl_type = None
    obj = WildlandObject.from_manifest(manifest, client, wl_type)

    if isinstance(obj, Container):
        for backend in obj.load_storages(include_url=False):
            backend.validate()


@click.command(short_help='Wildland version')
def version():
    """
    Returns Wildland version
    """
    # Fallback version
    wildland_version = __version__
    commit_hash = None

    cmd = ["git", "describe", "--always"]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True,
                                cwd=Path(__file__).resolve().parents[1])
        output = result.stdout.decode('utf-8').strip('\n')
        # version 'vX.Y.Z' or 'vX.Y.Z-L-g<ABBREVIATED_COMMIT_HASH>'
        version_regex = r'v(([0-9]+\.[0-9]+\.[0-9]+)(-[0-9]+-g([0-9a-f]+))?)$'
        parsed_output = re.match(version_regex, output)
        if parsed_output:
            wildland_version = parsed_output.group(2)
            if len(parsed_output.groups()) == 4:
                commit_hash = parsed_output.group(4)
    except subprocess.CalledProcessError:
        pass
    if commit_hash:
        wildland_version = f"{wildland_version} (commit {commit_hash})"
    print(wildland_version)


@click.command(short_help='manifest signing tool')
@click.option('-o', 'output_file', metavar='FILE', help='output file (default is stdout)')
@click.option('-i', 'in_place', is_flag=True, help='modify the file in place')
@click.argument('input_file', metavar='FILE', required=False)
@click.pass_context
def sign(ctx: click.Context, input_file, output_file, in_place):
    """
    Sign a manifest given by FILE, or stdin if not given. The input file can be
    a manifest with or without header. The existing header will be ignored.

    If invoked with manifest type (``user sign``, etc.), the will also validate
    the manifest against schema.
    """
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name if ctx.parent else None
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

    manifest = Manifest.from_unsigned_bytes(data, obj.client.session.sig)
    manifest.skip_verification()
    if manifest_type:
        try:
            validate_manifest(manifest, manifest_type, obj.client)
        except SchemaError as se:
            raise CliError(f'Invalid manifest: {se}') from se

    if manifest_type == 'user' or manifest.fields.get('object') == 'user':
        # for user manifests, allow loading keys for signing even if the manifest was
        # previously malformed and couldn't be loaded
        obj.client.session.sig.use_local_keys = True

    manifest.encrypt_and_sign(obj.client.session.sig,
                              only_use_primary_key=(manifest_type == 'user'))
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
def verify(ctx: click.Context, input_file):
    """
    Verify a manifest signature given by FILE, or stdin if not given.

    If invoked with manifests type (``user verify``, etc.), the command will
    also validate the manifest against schema.
    """
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name if ctx.parent else None
    if manifest_type == 'main':
        manifest_type = None

    if input_file:
        path = find_manifest_file(obj.client, input_file, manifest_type)
        data = path.read_bytes()
    else:
        data = sys.stdin.buffer.read()

    try:
        manifest = Manifest.from_bytes(data, obj.client.session.sig,
                                       allow_only_primary_key=(manifest_type == 'user'))
        if manifest_type:
            validate_manifest(manifest, manifest_type, obj.client)
    except (ManifestError, SchemaError) as e:
        raise click.ClickException(f'Error verifying manifest: {e}')
    click.echo('Manifest is valid')


@click.command(short_help='verify and dump contents of specified file')
@click.option('--decrypt/--no-decrypt', '-d/-n', default=True,
              help='decrypt manifest (if applicable)')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def dump(ctx: click.Context, input_file, decrypt, **_callback_kwargs):
    """
    Dump the input manifest in a machine-readable format (currently just json). By default decrypts
    the manifest, if possible.
    """
    obj: ContextObj = ctx.obj

    if obj.client.is_url(input_file):
        raise CliError('This command supports only an absolute path to a file. Consider using '
                       'dump command for a specific object, e.g. wl container dump')

    manifest_type = ctx.parent.command.name if ctx.parent else None
    if manifest_type == 'main':
        manifest_type = None

    path = find_manifest_file(obj.client, input_file, manifest_type)

    if decrypt:
        manifest = Manifest.from_file(path, obj.client.session.sig)
        data = yaml.dump(manifest.fields, encoding='utf-8', sort_keys=False)
    else:
        data = path.read_bytes()
        if HEADER_SEPARATOR in data:
            _, data = split_header(data)
    print(data.decode())


@click.command(short_help='edit manifest in external tool')
@click.option('--editor', metavar='EDITOR', help='custom editor')
@click.option('--remount/--no-remount', '-r/-n', default=True, help='remount mounted container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def edit(ctx: click.Context, editor: Optional[str], input_file: str, remount: bool,
         **_callback_kwargs: Any) -> bool:
    """
    Edit and sign a manifest in a safe way. The command will launch an editor
    and validate the edited file before signing and replacing it.

    Returns True iff the manifest was successfully modified (to be able to
    determine if it should be republished).
    """
    obj: ContextObj = ctx.obj

    if obj.client.is_url(input_file):
        raise CliError('This command supports only an local path to a file. Consider using '
                       'edit command for a specific object, e.g. wl container edit')

    provided_manifest_type = ctx.parent.command.name if ctx.parent else None
    if provided_manifest_type == 'main':
        provided_manifest_type = None

    path = find_manifest_file(obj.client, input_file, provided_manifest_type)

    try:
        manifest = Manifest.from_file(path, obj.client.session.sig)
        manifest_type = manifest.fields['object']
        data = yaml.dump(manifest.fields, encoding='utf-8', sort_keys=False)
    except ManifestError:
        data = path.read_bytes()
        manifest_type = provided_manifest_type

    if HEADER_SEPARATOR in data:
        _, data = split_header(data)

    data = b'# All YAML comments will be discarded when the manifest is saved\n' + data
    original_data = data

    new_manifest = None
    while not new_manifest:
        edited_s = click.edit(data.decode(), editor=editor, extension='.yaml',
                              require_save=False)
        assert edited_s
        data = edited_s.encode()

        if original_data == data:
            click.echo('No changes detected, not saving.')
            return False

        try:
            manifest = Manifest.from_unsigned_bytes(data, obj.client.session.sig)
            manifest.skip_verification()
        except (ManifestError, WildlandError) as e:
            click.secho(f'Manifest parse error: {e}', fg="red")
            if click.confirm('Do you want to edit the manifest again to fix the error?'):
                continue
            click.echo('Changes not saved.')
            return False

        if manifest_type is not None:
            try:
                validate_manifest(manifest, manifest_type, obj.client)
            except (SchemaError, ManifestError, WildlandError) as e:
                click.secho(f'Manifest validation error: {e}', fg="red")
                if click.confirm('Do you want to edit the manifest again to fix the error?'):
                    continue
                click.echo('Changes not saved.')
                return False
        if manifest_type == 'user':
            # for user manifests, allow loading keys for signing even if the manifest was
            # previously malformed and couldn't be loaded
            obj.client.session.sig.use_local_keys = True

        try:
            manifest.encrypt_and_sign(obj.client.session.sig,
                                      only_use_primary_key=(manifest_type == 'user'))
        except SigError as se:
            raise CliError(f'Cannot save manifest: {se}') from se

        new_manifest = manifest

    signed_data = new_manifest.to_bytes()
    with open(path, 'wb') as f:
        f.write(signed_data)
    click.echo(f'Saved: {path}')

    if remount and manifest_type == 'container' and obj.fs_client.is_running():
        path = find_manifest_file(obj.client, input_file, provided_manifest_type)
        remount_container(obj, path)

    return True


def remount_container(ctx_obj: ContextObj, path: Path):
    """
    Remount container given by path.
    """
    container = ctx_obj.client.load_object_from_file_path(WildlandObject.Type.CONTAINER, path)
    if ctx_obj.fs_client.find_primary_storage_id(container) is not None:
        click.echo('Container is mounted, remounting')

        user_paths = ctx_obj.client.get_bridge_paths_for_user(container.owner)
        storages = ctx_obj.client.get_storages_to_mount(container)

        ctx_obj.fs_client.mount_container(container, storages, user_paths, remount=True)


def modify_manifest(pass_ctx: click.Context, input_file: str, edit_funcs: List[Callable[..., dict]],
                    *, remount: bool = True, **kwargs) -> bool:
    """
    Edit manifest (identified by `name`) fields using a specified callback.

    @param pass_ctx: click context
    @param input_file: manifest file name
    @param edit_funcs: callbacks function to modify manifest.
    This module provides four common callbacks:
    - `add_field`,
    - `del_field`,
    - `set_field`,
    - `del_nested_field`.
    @param remount: default True: modified manifest is remounted
    @param kwargs: params for callbacks
    @return: Returns True iff the manifest was successfully modified (to be able to
    determine if it should be republished).
    """
    obj: ContextObj = pass_ctx.obj

    manifest_type = pass_ctx.parent.command.name if pass_ctx.parent else None
    if manifest_type == 'main':
        manifest_type = None

    manifest_path = find_manifest_file(obj.client, input_file, manifest_type)

    sig_ctx = obj.client.session.sig
    manifest = Manifest.from_file(manifest_path, sig_ctx)
    if manifest_type is not None:
        validate_manifest(manifest, manifest_type, obj.client)

    # the manifest is edited by edit_func below
    orig_manifest = copy.deepcopy(manifest)
    fields = manifest.fields
    for edit_func in edit_funcs:
        fields = edit_func(fields, **kwargs)
    modified_manifest = Manifest.from_fields(fields)

    orig_manifest_data = yaml.safe_dump(
        orig_manifest.fields, encoding='utf-8', sort_keys=False)
    modified_manifest_data = yaml.safe_dump(
        modified_manifest.fields, encoding='utf-8', sort_keys=False)

    if orig_manifest_data == modified_manifest_data:
        click.echo('Manifest has not changed.')
        return False

    if manifest_type is not None:
        try:
            validate_manifest(modified_manifest, manifest_type, obj.client)
        except SchemaError as se:
            raise CliError(f'Invalid manifest: {se}') from se

    modified_manifest.encrypt_and_sign(sig_ctx, only_use_primary_key=(manifest_type == 'user'))

    signed_data = modified_manifest.to_bytes()
    with open(manifest_path, 'wb') as f:
        f.write(signed_data)

    click.echo(f'Saved: {manifest_path}')

    if remount and manifest_type == 'container' and obj.fs_client.is_running():
        path = find_manifest_file(obj.client, input_file, 'container')
        remount_container(obj, path)

    return True


def add_fields(fields: dict, to_add: Dict[str, List[Any]], **_kwargs) -> dict:
    """
    Callback function for `modify_manifest`. Adds values to the specified field.
    Duplicates are ignored.
    """
    for field, values in to_add.items():
        fields.setdefault(field, [])

        for value in values:
            if value not in fields[field]:
                fields[field].append(value)
            else:
                click.echo(f'{value} is already in the manifest')
                continue

    return fields


def del_nested_fields(fields: dict, to_del_nested: Dict[Tuple, List[Any]],
                      **_kwagrs) -> dict:
    """
    Callback function for `modify_manifest` which is a wrapper for del_field callback
    for nested fields.

    >>> del_nested_fields(fields, {('backends', 'storage'): [0, 1, 2]})
    is equivalent of:
    >>> del fields['backends']['storage'][0]
    ... del fields['backends']['storage'][1]
    ... del fields['backends']['storage'][2]
    """
    for fs, keys in to_del_nested.items():

        # Going deeper into nested fields down to the last field (dict).
        subfields = fields
        for field in fs[:-1]:
            sf = subfields.get(field)
            if isinstance(sf, dict):
                subfields = sf
            else:
                raise CliError(
                    f'Field [{field}] either does not exist or is not a dictionary. Terminating.')

        # Removing keys from the inner dict
        del_fields(subfields, {fs[-1]: keys}, by_value=False)

    return fields


def del_fields(fields: dict, to_del: Dict[str, List[Any]], by_value: bool = True, **_kwargs) \
        -> dict:
    """
    Callback function for `modify_manifest`. Removes values from a list or a set either by values
    or keys. Non-existent values or keys are ignored.
    """
    for field, values_or_key in to_del.items():
        if by_value:
            keys = []
            values = values_or_key
        else:
            keys = values_or_key
            values = []

        obj = fields.get(field)

        if isinstance(obj, list):
            obj = dict(zip(range(len(obj)), obj))
            new_dict = _del_keys_and_values_from_dict(obj, keys, values)
            fields[field] = list(new_dict.values())
        elif isinstance(obj, dict):
            fields[field] = _del_keys_and_values_from_dict(obj, keys, values)
        else:
            cli_warn(f'Given field [{field}] is neither list, dict or does not exist. '
                       'Nothing is deleted.')

    return fields


def _del_keys_and_values_from_dict(dictionary: Dict[Any, Any], keys: Any, values: Any):
    skipped_positions = [key for key in keys if key not in dictionary]
    if skipped_positions:
        cli_warn(f'Given positions {skipped_positions} do not exist. Skipped.')

    skipped_values = [v for v in values if v not in dictionary.values()]
    if skipped_values:
        cli_warn(f'{skipped_values} are not in the manifest. Skipped.')

    return {k: v for k, v in dictionary.items() if k not in keys and v not in values}


def set_fields(fields: dict, to_set: Dict[str, str], **_kwargs) -> dict:
    """
    Callback function for `modify_manifest`. Sets value of the specified field.
    """
    fields.update(to_set)

    return fields


def check_if_any_options(ctx: click.Context, *args):
    """
    Raise CliError if all options are empty.
    """
    help_message = ""
    if ctx.parent:
        help_message += f"\nTry 'wl {ctx.parent.command.name} modify --help' for help."
    if not any(args):
        raise CliError('no option specified.' + help_message)


def check_options_conflict(option_name: str, add_option: List[str], del_option: List[str]):
    """
    Checks whether we want to add and remove the same field at the same time.

    Raise CliError when it finds conflict.

    @param option_name: e.g., 'path', 'category'
    @param add_option: values to add
    @param del_option: values to del
    """
    conflicts = set(add_option).intersection(del_option)
    if conflicts:
        message = "options conflict:"
        for c in conflicts:
            message += f'\n  --add-{option_name} {c} and --del-{option_name} {c}'
        raise CliError(message)
