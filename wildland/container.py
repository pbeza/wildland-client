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
The container
'''

from pathlib import PurePosixPath, Path
import uuid
from typing import Optional, List, Union
import itertools

from .manifest.manifest import Manifest
from .manifest.schema import Schema


class Container:
    '''Wildland container'''
    SCHEMA = Schema('container')

    def __init__(self, *,
                 owner: str,
                 paths: List[PurePosixPath],
                 backends: List[Union[str, dict]],
                 title: Optional[str] = None,
                 categories: Optional[List[PurePosixPath]] = None,
                 local_path: Optional[Path] = None):
        self.owner = owner
        self.paths = paths
        self.backends = backends
        self.title = title
        self.categories = categories if categories else []
        self.local_path = local_path
        self._expanded_paths: Optional[List[PurePosixPath]] = None

    def ensure_uuid(self) -> str:
        '''
        Find or create an UUID path for this container.
        '''

        for path in self.paths:
            if path.parent == PurePosixPath('/.uuid/'):
                return path.name
        ident = str(uuid.uuid4())
        self.paths.insert(0, PurePosixPath('/.uuid/') / ident)
        return ident

    @classmethod
    def from_manifest(cls, manifest: Manifest, local_path=None) -> 'Container':
        '''
        Construct a Container instance from a manifest.
        '''

        manifest.apply_schema(cls.SCHEMA)
        return cls(
            owner=manifest.fields['owner'],
            paths=[PurePosixPath(p) for p in manifest.fields['paths']],
            backends=manifest.fields['backends']['storage'],
            title=manifest.fields.get('title', None),
            categories=[Path(p) for p in manifest.fields.get('categories', [])],
            local_path=local_path,
        )

    def to_unsigned_manifest(self) -> Manifest:
        '''
        Create a manifest based on Container's data.
        Has to be signed separately.
        '''

        manifest = Manifest.from_fields(dict(
            owner=self.owner,
            paths=[str(p) for p in self.paths],
            backends={'storage': self.backends},
            title=self.title,
            categories=[str(cat) for cat in self.categories],
        ))
        manifest.apply_schema(self.SCHEMA)
        return manifest

    @property
    def expanded_paths(self):
        """
        Paths expanded by the set of paths generated from title and categories (if provided)
        """
        if self._expanded_paths:
            return self._expanded_paths
        paths = self.paths.copy()
        if self.title:
            for path in self.categories:
                paths.append(path / self.title)
            for p1, p2 in itertools.permutations(self.categories, 2):
                paths.append(p1 / p2.relative_to(p2.anchor) / self.title)
        self._expanded_paths = paths
        return self._expanded_paths
