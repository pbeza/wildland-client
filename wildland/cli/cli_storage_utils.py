from typing import Dict, Any, List, Union, Type

import click

from wildland.exc import WildlandError
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.file_children import FileChildrenMixin
from wildland.storage_backends.local import LocalStorageBackend
from wildland.storage_backends.local_cached import BaseCached
from wildland.storage_backends.static import StaticStorageBackend


def get_storage_cli_options(backend: Type[StorageBackend]) -> List[click.Option]:
    if backend.TYPE == FileChildrenMixin.TYPE:
        opts = [
            click.Option(['--subcontainer-manifest'], metavar='PATH', multiple=True,
                         help='Relative path to a child manifest (can be repeated), '
                              'cannot be used together with manifest-pattern'),
            click.Option(['--manifest-pattern'], metavar='GLOB',
                         help='Set the manifest pattern for storage, cannot be used '
                              'together with --subcontainer-manifest')]
        return opts

    if backend.TYPE == LocalStorageBackend.TYPE:
        opts = get_storage_cli_options(FileChildrenMixin)
        opts.append(click.Option(['--location'], metavar='PATH', help='path in local filesystem',
                                 required=True))
        return opts

    if backend.TYPE == BaseCached.TYPE:
        opts = [
            click.Option(['--location'], metavar='PATH', help='path in local filesystem',
                         required=True)
        ]
        return opts

    if backend.TYPE == StaticStorageBackend.TYPE:
        opts = [
            click.Option(['--file'], metavar='PATH=CONTENT',
                         help='File to be placed in the storage', multiple=True),
        ]
        return opts

    return []


def parse_cli_params(backend: Type[StorageBackend], data: Dict[str, Any]):
    if backend.TYPE == FileChildrenMixin.TYPE:
        result: Dict[str, Union[Dict, str]] = {}
        if data.get('subcontainer_manifest'):
            if data.get('manifest_pattern'):
                raise WildlandError('--subcontainer-manifest and --manifest-pattern '
                                    'are mutually exclusive.')
            result['manifest-pattern'] = {
                'type': 'list',
                'paths': list(data['subcontainer_manifest'])
            }
        elif data.get('manifest_pattern'):
            result['manifest-pattern'] = {
                'type': 'glob',
                'path': data['manifest_pattern']
            }
        return result

    if backend.TYPE == LocalStorageBackend.TYPE:
        result = parse_cli_params(FileChildrenMixin, data)
        result['location'] = data['location']
        return result

    if backend.TYPE == BaseCached.TYPE:
        return {'location': data['location']}

    if backend.TYPE == StaticStorageBackend.TYPE:
        content: Dict[str, Union[Dict, str]] = {}
        for file in data['file']:
            path, data = file.split('=', 1)
            path_parts = path.split('/')
            content_place: Dict[str, Any] = content
            for part in path_parts[:-1]:
                content_place = content_place.setdefault(part, {})
            content_place[path_parts[-1]] = data
        return {
            'content': content,
        }

    return data