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
ProxyS3 storage backend
'''

import errno
import logging
import mimetypes
import os
import threading
import time
from pathlib import PurePosixPath
from typing import Iterable, Tuple, Set

import botocore
import click

from wildland.manifest.schema import Schema
from wildland.storage_backends.base import Attr
from wildland.storage_backends.buffered import File
from wildland_s3.backend import S3StorageBackend, S3File

from .reauth_session import Session


logger = logging.getLogger('storage-proxys3')


class ProxyS3StorageBackend(S3StorageBackend):
    '''
    Amazon S3 stroage accesssed via re-auth proxy.
    No direct access is possible.
    '''

    SCHEMA = Schema({
        "title": "Storage manifest (S3 via re-auth proxy)",
        "type": "object",
        "required": ["proxy", "cert", "credentials"],
        "properties": {
            "proxy": {
                "type": "string",
                "description": "ProxyS3 IP address with port number"
            },
            "cert": {
                "type": "string",
                "description": "Absolute path to public SSL cert file",
            },
            "credentials": {
                "type": "object",
                "required": ["username", "password"],
                "properties": {
                    "username": {"type": "string"},
                    "password": {"type": "string"}
                },
                "additionalProperties": False
            }
        }
    })
    TYPE = 'proxys3'

    INDEX_NAME = 'index.html'

    def __init__(self, **kwds) -> None:
        super(S3StorageBackend, self).__init__(**kwds)

        self.with_index = self.params.get('with-index', False)

        proxy = self.params['proxy_address']
        cert = self.params['ssl_cert']
        credentials = self.params['credentials']
        session = Session(
            username=credentials['username'],
            password=credentials['password']
        )
        config = botocore.config.Config(
            region_name='proxys3',
            signature_version='proxy-basic',
            proxies={'https': proxy}
        )
        self.client = session.client('s3', verify=cert, config=config)

        # pylint: disable=no-member
        self.bucket = 'dummy-bucket'
        self.base_path = PurePosixPath('/') / credentials['username']

        # Persist created directories. This is because S3 doesn't have
        # information about directories, and we might want to create/remove
        # them manually.
        self.s3_dirs_lock = threading.Lock()
        self.s3_dirs: Set[PurePosixPath] = {PurePosixPath('.')}

        mimetypes.init()

    @classmethod
    def cli_options(cls):
        return [
            click.Option(
                ['--proxy'],
                help="ProxyS3 IP address with port number in format <IP>:<PORT>",
                required=True),
            click.Option(
                ['--cert'],
                help="Path to public SSL cert file",
                required=True),
            click.Option(['--username'], required=True),
            click.Option(['--password'], required=True),
            click.Option(['--with-index'], is_flag=True,
                         help='Maintain index.html files with directory listings')
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'proxy': data['proxy'],
            'ssl_cert': data['cert'],
            'credentials': {
                'username': data['username'],
                'password': data['password']
            },
            'with-index': data['with_index'],
        }

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        new_s3_dirs = set()

        token = None
        while True:
            if token:
                resp = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=self.base_path.relative_to('/').as_posix(),
                    ContinuationToken=token,
                )
            else:
                resp = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=self.base_path.relative_to('/').as_posix()
                )

            for summary in resp.get('Contents', []):

                full_path = PurePosixPath('/') / summary['Key']
                try:
                    obj_path = full_path.relative_to(self.base_path)
                except ValueError:
                    continue

                if not (self.with_index and obj_path.name == self.INDEX_NAME):
                    yield obj_path, self._stat(summary)
                
                # Add path to s3_dirs even if we just see index.html.
                for parent in obj_path.parents:
                    new_s3_dirs.add(parent)

            if resp['IsTruncated']:
                token = resp['NextContinuationToken']
            else:
                break

        # In case we haven't found any files
        new_s3_dirs.add(PurePosixPath('.'))

        with self.s3_dirs_lock:
            self.s3_dirs.update(new_s3_dirs)
            all_s3_dirs = list(self.s3_dirs)

        for dir_path in all_s3_dirs:
            yield dir_path, Attr.dir()

    def create(self, path: PurePosixPath, _flags: int, _mode: int) -> File:
        if self.with_index and path_name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        content_type = self.get_content_type(path)
        logger.debug('creating %s with content type %s', path, content_type)
        
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=self.key(path),
                ContentType=content_type)
        # In case a quota has been exceeded
        except botocore.exceptions.ClientError as err:
            raise IOError(errno.ENOSPC, str(err))

        attr = Attr.file(size=0, timestamp=int(time.time()))
        self.clear_cache()
        self._update_index(path.parent) 
        return S3File(self.client, self.bucket, self.key(path),
                      content_type, attr)
