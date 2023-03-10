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
Timeline backend
"""

import uuid
from typing import Tuple, Optional, Iterable
from pathlib import PurePosixPath
import errno
import datetime

import click

from .base import StorageBackend, File, Attr
from .cached import CachedStorageMixin
from ..manifest.schema import Schema
from ..container import ContainerStub
from ..wildland_object.wildland_object import WildlandObject


class TimelineStorageBackend(CachedStorageMixin, StorageBackend):
    """
    A proxy storage that re-organizes the files into directories based on their
    modification date.

    All files will have a 'year/month/day' prefix prepended to their path.
    Directory timestamps will be ignored, and empty directories will not be
    taken into account.

    The 'reference-container' parameter specifies inner container, either as URL,
    or as an inline manifest. When creating the object instance:

    1. First, the storage parameters for the inner container will be resolved
    (see Client.select_storage()),

    2. Then, the inner storage backend will be instantiated and passed as
    params['storage'] (see StorageBackend.from_params()).
    """

    SCHEMA = Schema({
        "type": "object",
        "required": ["reference-container"],
        "properties": {
            "reference-container": {
                "$ref": "/schemas/types.json#reference-container",
                "description": ("Container to be used, either as URL "
                                "or as an inlined manifest"),
            },
            "timeline-root": {
                "type": ["string", "null"],
                "description": ("Configurable directory to be used as a the root "
                                "of the timeline tree generated by the backend"),
            },
        }
    })
    TYPE = 'timeline'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.inner = self.params['storage']
        self.reference = self.params['reference-container']
        self.root = self.params.get('timeline-root', '/timeline')
        self.read_only = True

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'], metavar='URL',
                         help='URL for inner container manifest',
                         required=True),
            click.Option(['--timeline-root'], required=False,
                         default='/timeline',
                         help='The name of the root of the timeline tree'),
        ]

    @classmethod
    def cli_create(cls, data):
        return {'reference-container': data['reference_container_url'],
                'timeline-root': data['timeline_root']}

    def mount(self):
        self.inner.request_mount()

    def unmount(self):
        self.inner.request_unmount()

    def clear_cache(self):
        self.inner.clear_cache()

    @staticmethod
    def _split_path(path: PurePosixPath) -> Tuple[Optional[str], PurePosixPath]:
        """
        Extract the prefix part (first 3 parts) from path. For correct
        user requests, the prefix will be a date, but it needs to be verified
        (i.e. compared with the right date).

            >>> _split_path(PurePosixPath('2020/10/10/foo/bar.txt')
            ('2020/10/10', PurePosixPath('foo/bar.txt'))

            >>> _split_path(PurePosixPath('2020/10/foo.txt')
            (None, PurePosixPath('2020/10/foo.txt'))
        """
        # As the backend creates separate subcontainers for each of the files,
        # the creation of separate 'name' directories for each of the files in
        # the parent container is necessary.
        # Thus, as to access the content of the actual file (via it's initial
        # path) we need to remove those 'name' directories (or the part of the
        # directory that is a duplicate of the file's name).
        name_duplicate = len(path.parts) - 1

        if len(path.parts) <= 3:
            return None, path

        # The duplicated 'name' part of the path is discarded.
        prefix, suffix, _ = path.parts[:3], path.parts[3:name_duplicate], \
                            path.parts[name_duplicate]
        date = '/'.join(prefix)
        return date, PurePosixPath(*suffix)

    @staticmethod
    def _date_str(timestamp: int) -> str:
        d = datetime.date.fromtimestamp(timestamp)
        return f'{d.year:04}/{d.month:02}/{d.day:02}'

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        yield from self._info_all_walk(PurePosixPath('.'))

    def _info_all_walk(self, dir_path: PurePosixPath) -> \
            Iterable[Tuple[PurePosixPath, Attr]]:

        for name in self.inner.readdir(dir_path):
            path = dir_path / name
            attr = self.inner.getattr(path)
            if attr.is_dir():
                yield from self._info_all_walk(path)
            else:
                date_str = self._date_str(attr.timestamp)
                # Duplicating the 'name' to create a separate directory for each
                # file. This is necessary for the delegate backend to be able
                # to access each of the files individually and prevents
                # unneccessary file duplicates in the timeline tree.
                yield date_str / path / PurePosixPath(name), attr

    def open(self, path: PurePosixPath, flags: int) -> File:
        date_str, inner_path = self._split_path(path)
        if date_str is None:
            raise IOError(errno.ENOENT, str(path))
        attr = self.inner.getattr(inner_path)
        actual_date_str = self._date_str(attr.timestamp)
        if date_str != actual_date_str:
            raise IOError(errno.ENOENT, str(path))

        return self.inner.open(inner_path, flags)

    @property
    def can_have_children(self) -> bool:
        return True

    def get_children(
            self,
            client=None,
            query_path: PurePosixPath = PurePosixPath('*'),
            paths_only: bool = False
    ) -> Iterable[Tuple[PurePosixPath, Optional[ContainerStub]]]:

        ns = uuid.UUID(self.backend_id)

        # resolving the reference-container to gain access to its categories
        if not paths_only:
            if isinstance(self.reference, str):
                # pylint: disable=line-too-long
                ref_container = client.load_object_from_url(
                    object_type=WildlandObject.Type.CONTAINER,
                    url=self.reference,
                    owner=self.params['owner'])
                ref_categories = ref_container.categories
            else:
                ref_categories = self.reference.get('categories', [])

        for file, _ in self.info_all():
            stub_categories = []
            date = self._split_path(file)[0]
            assert file.name is not None
            name = file.name

            if not paths_only:
                for category in ref_categories:
                    stub_categories.append(self.root + '/' + date + str(category))

                yield PurePosixPath(self.root + '/' + date + '/' + name), \
                      ContainerStub({
                          'paths': [
                              '/.uuid/{!s}'.format(uuid.uuid3(ns, name)),
                              self.root + '/' + date,
                          ],
                          'title': file.name,
                          'categories': stub_categories,
                          'backends': {'storage': [{
                              'type': 'delegate',
                              'reference-container': 'wildland:@default:@parent-container:',
                              'subdirectory': '/' + str(file.parent),
                              'backend-id': str(uuid.uuid3(ns, name))
                          }]}
                      })
            else:
                yield PurePosixPath(self.root + '/' + date + '/' + name), None
