"""
Google Photos backend used to expose a google photos library as
a Wildland container.
"""

#pylint: disable=too-many-arguments
import stat
from pathlib import PurePosixPath
import json
from datetime import datetime
import logging
from typing import Optional, Callable, Iterable, Tuple

import click

from google_auth_oauthlib.flow import InstalledAppFlow
from wildland.storage_backends.buffered import FullBufferedFile
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.storage_backends.file_subcontainers import FileSubcontainersMixin
from wildland.manifest.schema import Schema
from .photos_client import PhotosClient

logger = logging.getLogger('googlephotos-backend')
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

class PhotosFile(FullBufferedFile):
    """
    Representation of a Google Photos file.
    """

    def __init__(self, client: PhotosClient, base_url: str, maxw: int,
                 maxh: int, attr: Attr, clear_cache_callback: Optional[Callable] = None):
        super().__init__(attr, clear_cache_callback)
        self.client = client
        self.base_url = base_url
        self.attr = attr
        self.maxw = maxw
        self.maxh = maxh

    def read_full(self) -> bytes:
        return self.client.get_file_content(self.base_url, self.maxw, self.maxh)

    def write_full(self, data: bytes):
        pass

class GooglePhotosBackend(FileSubcontainersMixin, DirectoryCachedStorageMixin, StorageBackend):
    """
    Google Photos backend supporting read only operations.
    """
    SCHEMA = Schema({
                "title": "Google Photos storage manifest",
                "type": "object",
                "required": ["credentials"],
                "properties": {
                    "credentials": {
                        "type": "object",
                        "required": [
                            "token",
                            "refresh_token",
                            "token_uri",
                            "client_id",
                            "client_secret",
                            "scopes",
                        ],
                    },
                    "manifest-pattern": {
                        "oneOf": [
                            {"$ref": "/schemas/types.json#pattern-glob"},
                            {"$ref": "/schemas/types.json#pattern-list"},
                        ]
                    },
                }
            })
    TYPE = 'googlephotos'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        photos_access_credentials = self.params.get('credentials')
        self.client = PhotosClient(photos_access_credentials)
        self.albums = {}
        self.all_items = {}

    @classmethod
    def cli_options(cls):
        opts = super(GooglePhotosBackend, cls).cli_options()
        opts.extend(
            [
                click.Option(
                    ['--credentials'], required=True,
                    help='Google Photos credentials necessary for authorization purposes'
                ),
                click.Option(
                ['--skip-interaction'], default=False, is_flag=True,
                required=False,
                help='Pass token as credential and pass this flag to skip interaction'
                ),
            ]
        )
        return opts

    @classmethod
    def cli_create(cls, data):
        credentials = None
        client_config = json.loads(data['credentials'])
        if data['skip_interaction']:
            credentials = client_config
        else:
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            credentials = flow.run_console()
            credentials = json.loads(credentials.to_json())

        result = super(GooglePhotosBackend, cls).cli_create(data)
        result.update({'location': data['location'], 'credentials': credentials})
        return result

    def mount(self) -> None:
        """
        Mounts the container by calling the connect() method in the client
        """
        logger.debug('Mounting the container')
        self.client.connect()

    def unmount(self) -> None:
        """
        Unmounts the container by calling the disconnect() method in the client
        """
        logger.debug('Unmounting the container')
        self.client.disconnect()
        self.albums = {}
        self.all_items = {}

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, Attr]]:
        """
        Given a path, returns a list of objects (files, directories) that
        should be shown under it.
        """
        logger.debug('Fetching information about %s', str(path))
        if path in (PurePosixPath('/'), PurePosixPath('.')):
            self.albums = self.client.get_album_dict()
            self.albums['Library'] = ''
            for album_name in self.albums.keys():
                folder_attr = Attr(mode = stat.S_IFDIR | 0o755,
                                             size = 0,
                                             timestamp = 0)
                yield album_name, folder_attr
        else:
            album = self.get_album_from_path(path)
            photos = self.client.get_photos_from_album(self.albums[album])
            for item in photos:
                #saving the items in a 'cache'
                self.all_items[item['filename']] = item
                to_parse = item['mediaMetadata']['creationTime'].replace('Z','+00:00')
                date = datetime.fromisoformat(to_parse)
                item_attr = Attr(mode = stat.S_IFREG | 0o444,
                                 size = self.client.get_item_size(item['baseUrl']),
                                 timestamp = int(datetime.timestamp(date)))
                yield item['filename'], item_attr

    def open(self, path: PurePosixPath, _flags: int) -> PhotosFile:
        """
        Given the path leading to a file, returns a representation of that file,
        including the data stored in it.
        """
        logger.debug('Opening the file under the %s path', str(path))
        item = self.all_items[path.name]
        date = datetime.fromisoformat(item['mediaMetadata']['creationTime'].replace('Z','+00:00'))
        attr = Attr(mode = stat.S_IFREG | 0o444,
                    size = self.client.get_item_size(item['baseUrl']),
                    timestamp = int(datetime.timestamp(date)))

        return PhotosFile(client = self.client,
                          base_url = item['baseUrl'],
                          maxw = item['mediaMetadata']['width'],
                          maxh = item['mediaMetadata']['height'],
                          attr = attr)

    @classmethod
    def get_album_from_path(cls, path: PurePosixPath) -> Optional[str]:
        """
        Given a path, retrieves an album name corresponding to that path.
        This is necessary in order to retrieve a list of files stored in that
        album.
        """
        to_return = None
        for path_part in path.parts:
            if path_part in ('/', '.'):
                continue

            to_return = path_part

        return to_return
