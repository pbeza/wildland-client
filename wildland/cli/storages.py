import abc
from typing import Dict, Any, List, Union, Type

import click

from wildland.exc import WildlandError
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.file_children import FileChildrenMixin
from wildland.storage_backends.local import LocalStorageBackend
from wildland.storage_backends.local_cached import BaseCached
from wildland.storage_backends.static import StaticStorageBackend


class StorageBackendCli(StorageBackend, metaclass=abc.ABCMeta):
    def __init__(self, **kwds):
        super().__init__(**kwds)

    @classmethod
    def cli_options(cls) -> List[click.Option]:
        """
        Provide a list of command-line options needed to create this storage. If using mixins,
        check if a super() call is needed.
        """
        return []

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert provided command-line arguments to a list of storage parameters. If using mixins,
        check if a super() call is needed.
        """
        # pylint: disable=unused-argument
        return {}


class FileChildrenMixinCli(FileChildrenMixin, StorageBackendCli):
    @classmethod
    def cli_options(cls) -> List[click.Option]:
        result = super(FileChildrenMixinCli, cls).cli_options()
        result.append(
            click.Option(['--subcontainer-manifest'], metavar='PATH', multiple=True,
                         help='Relative path to a child manifest (can be repeated), '
                              'cannot be used together with manifest-pattern'))
        result.append(
            click.Option(['--manifest-pattern'], metavar='GLOB',
                         help='Set the manifest pattern for storage, cannot be used '
                              'together with --subcontainer-manifest'))
        return result

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        result = super(FileChildrenMixinCli, cls).cli_create(data)
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


class LocalStorageBackendCli(LocalStorageBackend, StorageBackendCli):
    def __init__(self, **kwds):
        super().__init__(**kwds)

    @classmethod
    def cli_options(cls):
        opts = super(LocalStorageBackendCli, cls).cli_options()
        opts.append(click.Option(['--location'], metavar='PATH', help='path in local filesystem',
                                 required=True))
        return opts

    @classmethod
    def cli_create(cls, data):
        result = super(LocalStorageBackendCli, cls).cli_create(data)
        result['location'] = data['location']
        return result


class BaseCachedCli(BaseCached, StorageBackendCli):
    def __init__(self, **kwds):
        super().__init__(**kwds)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--location'], metavar='PATH',
                         help='path in local filesystem',
                         required=True)
        ]

    @classmethod
    def cli_create(cls, data):
        return {'location': data['location']}


class StaticStorageBackendCli(StaticStorageBackend, StorageBackendCli):
    def __init__(self, **kwds):
        super().__init__(**kwds)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--file'], metavar='PATH=CONTENT',
                         help='File to be placed in the storage',
                         multiple=True),
        ]

    @classmethod
    def cli_create(cls, data):
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


def list_backends() -> Dict[str, Type[StorageBackendCli]]:
    backends: List[Type[StorageBackendCli]]
    backends = [LocalStorageBackendCli, BaseCachedCli, StaticStorageBackendCli]
    return {backend.TYPE: backend for backend in backends}
