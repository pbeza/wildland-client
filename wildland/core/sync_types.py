# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
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
Public API for Wildland sync operations - types.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List

from wildland.storage_sync.base import SyncEvent, SyncStateEvent, SyncProgressEvent, \
    SyncConflictEvent, SyncErrorEvent


# TODO merge SyncEvent and SyncApiEvent (after removing current sync daemon that needs SyncEvent)
class SyncApiEventType(Enum):
    """
    Type of sync event.
    """
    STATE = 1  # syncer state change
    PROGRESS = 2  # sync progress
    CONFLICT = 3  # sync conflict
    ERROR = 4  # sync error

    @staticmethod
    def from_raw(raw: SyncEvent) -> 'SyncApiEventType':
        """
        Get SyncApiEventType from low-level SyncEvent.
        """
        if isinstance(raw, SyncStateEvent):
            return SyncApiEventType.STATE
        if isinstance(raw, SyncProgressEvent):
            return SyncApiEventType.PROGRESS
        if isinstance(raw, SyncConflictEvent):
            return SyncApiEventType.CONFLICT
        if isinstance(raw, SyncErrorEvent):
            return SyncApiEventType.ERROR
        raise ValueError


@dataclass(frozen=True)
class SyncApiEvent:
    """
    Class representing a sync event.
    """
    container_id: str
    type: SyncApiEventType
    value: Any  # TODO?

    @staticmethod
    def from_raw(raw: SyncEvent) -> 'SyncApiEvent':
        """
        Convert SyncEvent to SyncApiEvent.
        """
        assert raw.job_id, f'No job_id in event {raw}'
        return SyncApiEvent(container_id=raw.job_id,
                            type=SyncApiEventType.from_raw(raw),
                            value=raw.value)


@dataclass
class SyncApiFileState:
    """
    Sync state of a single file.
    """
    path: str
    size: int
    synced: bool = True
    errors: List[SyncApiEvent] = field(default_factory=list)
    progress: int = 0
