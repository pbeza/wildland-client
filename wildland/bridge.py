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
Bridge manifest object
"""

from pathlib import PurePosixPath
from typing import Optional, List, Iterable, Union
from copy import deepcopy
from uuid import UUID, uuid5

from wildland.container import Container
from wildland.manifest.manifest import Manifest
from wildland.wildland_object.wildland_object import WildlandObject, PublishableWildlandObject
from wildland.manifest.schema import Schema
from wildland.exc import WildlandError

# An arbitrary UUID namespace, used to generate deterministic UUID of a bridge
# placeholder container. See `Bridge.to_placeholder_container()` below.
BRIDGE_PLACEHOLDER_UUID_NS = UUID('4a9a69d0-6f32-4ab5-8d4e-c198bf582554')


class Bridge(PublishableWildlandObject, obj_type=WildlandObject.Type.BRIDGE):
    """
    Bridge object: a wrapper for user manifests.
    """

    SCHEMA = Schema("bridge")

    def __init__(self,
                 owner: str,
                 user_location: Union[str, dict],
                 user_pubkey: str,
                 user_id: str,
                 paths: Iterable[PurePosixPath],
                 client,
                 manifest: Manifest = None):
        super().__init__()
        self.owner = owner
        self.user_location = deepcopy(user_location)
        self.user_pubkey = user_pubkey
        self.user_id = user_id
        self.manifest = manifest
        self.client = client
        self.paths: List[PurePosixPath] = list(paths)

    def get_unique_publish_id(self) -> str:
        return f'{self.user_id}.bridge'

    def get_primary_publish_path(self) -> PurePosixPath:
        return PurePosixPath('/.uuid/') / self.get_unique_publish_id()

    def get_publish_paths(self) -> List[PurePosixPath]:
        return [self.get_primary_publish_path()] + self.paths.copy()

    @staticmethod
    def create_safe_bridge_paths(user_id, paths) -> List[PurePosixPath]:
        """
        Creates safe (ie. obscure) bridge path which will not conflict with other potentially
        existing, user-defined paths which could cause mailicious forest to be mounted without
        user's awareness.
        """
        safe_paths = []

        for path in paths:
            if path.is_relative_to('/'):
                path = path.relative_to('/')

            safe_paths.append(PurePosixPath(f'/forests/{user_id}-' + '_'.join(path.parts)))

        return safe_paths

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest: Optional[Manifest] = None, **kwargs):
        return cls(
                owner=fields['owner'],
                user_location=fields['user'],
                user_pubkey=fields['pubkey'],
                user_id=client.session.sig.fingerprint(fields['pubkey']),
                paths=[PurePosixPath(p) for p in fields['paths']],
                client=client,
                manifest=manifest
            )

    def to_manifest_fields(self, inline: bool, str_repr_only: bool = False) -> dict:
        if inline:
            raise WildlandError('Bridge manifest cannot be inlined.')
        result = {
            "version": Manifest.CURRENT_VERSION,
            "object": WildlandObject.Type.BRIDGE.value,
            "owner": self.owner,
            "paths": [str(p) for p in self.paths],
            "user": deepcopy(self.user_location),
            "pubkey": self.user_pubkey,
        }
        self.SCHEMA.validate(result)
        return result

    def to_repr_fields(self, include_sensitive: bool = False) -> dict:
        # pylint: disable=unused-argument
        """
        This function provides filtered sensitive and unneeded fields for representation
        """
        # TODO: wildland/wildland-client/issues#563
        fields = self.to_manifest_fields(inline=False, str_repr_only=True)
        if not include_sensitive:
            if isinstance(fields["user"], dict):
                fields["user"].pop("storage", None)
        return fields

    def to_placeholder_container(self) -> Container:
        """
        Create a placeholder container that shows how to mount the target user's forest.
        """
        uuid = uuid5(BRIDGE_PLACEHOLDER_UUID_NS, self.user_id)
        return Container(
            owner=self.user_id,
            paths=[PurePosixPath('/.uuid/' + str(uuid)), PurePosixPath('/')],
            backends=[{
                'type': 'static',
                'backend-id': str(uuid),
                'content': {
                    'WILDLAND-FOREST.txt':
                        f'This directory holds forest of user {self.user_id}.\n'
                        f'Use \'wl forest mount\' command to get access to it.\n',
                }
            }],
            client=self.client
        )

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

    def __eq__(self, other):
        if not isinstance(other, Bridge):
            return NotImplemented
        return (self.owner == other.owner and
                self.user_pubkey == other.user_pubkey and
                set(self.paths) == set(other.paths) and
                self.user_location == other.user_location)

    def __hash__(self):
        return hash((
            self.owner,
            self.user_pubkey,
            frozenset(self.paths),
            repr(self.user_location),
        ))

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        if self._str_repr:
            return self._str_repr
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr = []
        if isinstance(fields["user"], str):
            array_repr += [f"user={fields['user']!r}"]
        elif isinstance(fields["user"], dict):
            link_array_repr = []
            for key, val in fields["user"].items():
                link_array_repr += [f"{key}={val!r}"]
            link_str_repr = "link(" + ", ".join(link_array_repr) + ")"
            array_repr += [f"user={link_str_repr}"]
        array_repr += [f"paths={[str(p) for p in fields['paths']]}"]
        self._str_repr = "bridge(" + ", ".join(array_repr) + ")"
        return self._str_repr
