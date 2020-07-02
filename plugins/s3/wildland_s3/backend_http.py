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
Indexed HTTP storage backend
'''

from pathlib import PurePosixPath
from typing import Iterable, Tuple
from urllib.parse import urljoin, urlparse, quote
import logging
from io import BytesIO

import click
import fuse
from lxml import etree
import requests

from wildland.storage_backends.util import simple_dir_stat, simple_file_stat
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.buffered import PagedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.manifest.schema import Schema


logger = logging.getLogger('storage-s3')


class PagedHttpFile(PagedFile):
    '''
    A read-only paged HTTP file.
    '''

    def __init__(self,
                 session: requests.Session,
                 url: str,
                 attr):
        super().__init__(attr)
        self.session = session
        self.url = url

    def read_range(self, length, start) -> bytes:
        range_header = 'bytes={}-{}'.format(start, start+length-1)

        resp = self.session.request(
            method='GET',
            url=self.url,
            headers={
                'Accept': '*/*',
                'Range': range_header
            }
        )
        resp.raise_for_status()
        return resp.content


class HttpIndexStorageBackend(DirectoryCachedStorageMixin, StorageBackend):
    '''
    A read-only HTTP storage that gets its information from directory listings.
    '''

    SCHEMA = Schema({
        "title": "Storage manifest (HTTP index)",
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "$ref": "types.json#http-url",
                "description": "HTTP URL pointing to an index",
            },
        }
    })
    TYPE = 'http-index'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.session = requests.Session()
        self.url = urlparse(self.params['url'])
        self.read_only = True

        self.base_url = self.params['url']
        self.base_path = PurePosixPath(urlparse(self.base_url).path)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--url'], metavar='URL', required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'url': data['url'],
        }

    def make_url(self, path: PurePosixPath) -> str:
        '''
        Convert a Path to resource URL.
        '''

        full_path = self.base_path / path
        return urljoin(self.base_url, quote(str(full_path)))

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, fuse.Stat]]:
        url = self.make_url(path)
        resp = self.session.request(
            method='GET',
            url=url,
            headers={
                'Accept': 'text/html',
            }
        )
        resp.raise_for_status()

        parser = etree.HTMLParser()
        tree = etree.parse(BytesIO(resp.content), parser)
        for a_element in tree.findall('.//a'):
            try:
                href = a_element.attrib['href']
            except KeyError:
                continue

            if urlparse(href).netloc:
                continue

            try:
                rel_path = PurePosixPath(href).relative_to(self.base_path)
            except ValueError:
                continue

            if rel_path.parent != path:
                continue

            if href.endswith('/'):
                attr = simple_dir_stat()
            else:
                attr = simple_file_stat(0, 0)

            yield rel_path.name, attr

    def open(self, path: PurePosixPath, flags: int) -> PagedHttpFile:
        url = self.make_url(path)
        resp = self.session.request(
            method='HEAD',
            url=url,
            headers={
                'Accept': '*/*',
            }
        )
        resp.raise_for_status()

        size = int(resp.headers['Content-Length'])
        attr = simple_file_stat(size, 0)
        return PagedHttpFile(self.session, url, attr)
