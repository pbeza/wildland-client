# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>,
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
Local storage, similar to :command:`mount --bind`
"""

from pathlib import PurePosixPath

from .base import StorageBackend, Attr
from ..manifest.schema import Schema
from ..log import get_logger

__all__ = ['DummyStorageBackend']

logger = get_logger('dummy-storage')


class DummyStorageBackend(StorageBackend):
    """Dummy storage"""
    SCHEMA = Schema({
        "type": "object",
        "required": [],
        "properties": {}
    })
    TYPE = 'dummy'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_only = True

    @classmethod
    def cli_options(cls):
        return []

    @classmethod
    def cli_create(cls, data):
        return {
            'subcontainers': list(data.get('subcontainer', [])),
        }

    def open(self, path, flags):
        raise FileNotFoundError

    def getattr(self, path):
        if path == PurePosixPath('.'):
            return Attr.dir()
        raise FileNotFoundError

    def readdir(self, path):
        if path == PurePosixPath('.'):
            return []
        raise FileNotFoundError
