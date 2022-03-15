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
API for Wildland sync operations.
"""
import abc
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple, Optional, Callable, Set, Dict

from wildland.core.wildland_result import WildlandResult
from wildland.storage_sync.base import SyncState, SyncConflict, SyncFileState, SyncEvent, \
    SyncStateEvent, SyncProgressEvent, SyncConflictEvent, SyncErrorEvent


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

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return self.__str__()


@dataclass(frozen=True)
class SyncApiEvent:
    """
    Class representing a sync event.
    """
    container_id: str
    type: SyncApiEventType
    state: Optional[SyncState] = None  # for STATE events
    progress: Optional[Tuple[str, int]] = None  # for PROGRESS events: path, progress%
    conflict: Optional[SyncConflict] = None  # for CONFLICT events
    error: Optional[str] = None  # for ERROR events

    @staticmethod
    def from_raw(raw: SyncEvent) -> 'SyncApiEvent':
        """
        Convert SyncEvent to SyncApiEvent.
        """
        assert raw.job_id, f'No job_id in event {raw}'
        if isinstance(raw, SyncStateEvent):
            return SyncApiEvent(container_id=raw.job_id,
                                type=SyncApiEventType.from_raw(raw),
                                state=raw.state)

        if isinstance(raw, SyncProgressEvent):
            return SyncApiEvent(container_id=raw.job_id,
                                type=SyncApiEventType.from_raw(raw),
                                progress=(str(raw.path), raw.progress))

        if isinstance(raw, SyncConflictEvent):
            return SyncApiEvent(container_id=raw.job_id,
                                type=SyncApiEventType.from_raw(raw),
                                conflict=raw.conflict)

        if isinstance(raw, SyncErrorEvent):
            return SyncApiEvent(container_id=raw.job_id,
                                type=SyncApiEventType.from_raw(raw),
                                error=raw.value)

        raise ValueError

    @property
    def value(self) -> str:
        """
        Return human-readable event data.
        """
        if self.state is not None:
            return str(self.state)

        if self.progress is not None:
            return f'{self.progress[1]}% {self.progress[0]}'

        if self.conflict is not None:
            return str(self.conflict)

        if self.error is not None:
            return self.error

        raise ValueError

    def __str__(self):
        return f'{self.type}: {self.value} ({self.container_id})'

    def __repr__(self):
        return self.__str__()


class WildlandSyncApi(metaclass=abc.ABCMeta):
    """
    Wildland sync API.
    """
    @abc.abstractmethod
    def syncer_start(self) -> WildlandResult:
        """
        Initialize sync manager, its threads if needed etc.
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def syncer_stop(self) -> WildlandResult:
        """
        Stop sync manager and all its jobs.
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def attach(self) -> WildlandResult:
        """
        Connect to sync manager, start it if not running. Needed before calling any sync methods.
        API implementations may start various threads in the background, call `detach()`
        to clean up gracefully after using API methods (otherwise current process may be waiting
        for these threads to end).
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def detach(self) -> WildlandResult:
        """
        Detach from sync manager.
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def start_container_sync(self, container_id: str, source_storage_id: str,
                             target_storage_id: str, continuous: bool, unidirectional: bool) \
            -> WildlandResult:
        """
        Start syncing given container. Asynchronous: sync job is started in the background
        and this method returns immediately.
        :param source_storage_id: storage id, in the format as in Wildland Core API, of the source
        storage (order of source/target is relevant only for unidirectional sync, which transfers
        data from source to target)
        :param target_storage_id: storage id, in the format as in Wildland Core API, of the target
        storage (order of source/target is relevant only for unidirectional sync, which transfers
        data from source to target)
        :param container_id: container id in the format as in Wildland Core API.
        :param continuous: should sync be continuous or one-shot
        :param unidirectional: should sync go both ways or one-way only
        :return: WildlandResult showing if it was successful.

        Note: one-shot sync is asynchronous too and needs to be stopped manually even if it reaches
              the SYNCED state. That's because the sync job is internally still kept to allow
              querying its state etc.
        """

    @abc.abstractmethod
    def stop_container_sync(self, container_id: str, force: bool = False) -> WildlandResult:
        """
        Stop syncing given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :param force: should stop be immediate or wait until the end of current syncing operation.
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def pause_container_sync(self, container_id: str) -> WildlandResult:
        """
        Pause syncing given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def resume_container_sync(self, container_id: str) -> WildlandResult:
        """
        Resume syncing given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def register_event_handler(self, container_id: Optional[str], filters: Set[SyncApiEventType],
                               callback: Callable[[SyncApiEvent], None]) \
            -> Tuple[WildlandResult, int]:
        """
        Register handler for events; only receives events listed in filters.
        Can be called before a sync is started for the given container.
        :param container_id: Container for which to receive events, all containers if None
        :param filters: Set of event types to be given to handler (empty means all)
        :param callback: function that takes SyncApiEvent as param and returns nothing
        :return: Tuple of WildlandResult and id of the registered handler.
        """

    @abc.abstractmethod
    def remove_event_handler(self, handler_id: int) -> WildlandResult:
        """
        De-register event handler with the provided id.
        :param handler_id: value returned by register_event_handler
        :return: WildlandResult showing if it was successful.
        """

    @abc.abstractmethod
    def get_current_sync_jobs(self) -> Tuple[WildlandResult, Dict[str, SyncState]]:
        """
        Get current state of all running sync jobs.
        :return: WildlandResult and dictionary {container_uuid: sync_state}.
        """

    @abc.abstractmethod
    def get_container_sync_state(self, container_id: str) -> \
            Tuple[WildlandResult, Optional[SyncState]]:
        """
        Get current state of sync of the given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult and overall state of the sync.
        """

    @abc.abstractmethod
    def get_container_sync_details(self, container_id: str) -> \
            Tuple[WildlandResult, List[SyncFileState]]:
        """
        Get current sync state of all files in the given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult and a list with states of all container files.
        """

    @abc.abstractmethod
    def get_container_sync_conflicts(self, container_id: str) -> \
            Tuple[WildlandResult, List[SyncConflict]]:
        """
        Get list of conflicts in given container's sync.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult and list of file conflicts.
        """

    @abc.abstractmethod
    def get_file_sync_state(self, container_id: str, path: str) -> \
            Tuple[WildlandResult, Optional[SyncFileState]]:
        """
        Get sync state of a given file.
        :param container_id: container_id in the format as in Wildland Core API.
        :param path: path to file in the container
        :return: WildlandResult and file state
        """

    @abc.abstractmethod
    def force_file_sync(self, container_id: str, path: str, source_storage_id: str,
                        target_storage_id: str) -> WildlandResult:
        """
        Force synchronize a file from one storage to another.
        :param container_id: container_id in the format as in Wildland Core API.
        :param path: path to file in container
        :param source_storage_id: id of the source storage (from where the authoritative file state
         should be taken) in the format as in Wildland Core API
        :param target_storage_id: id of the target storage (to where the file should be copied)
        in the format as in Wildland Core API
        :return: WildlandResult
        """

    @abc.abstractmethod
    def wait_for_sync(self, container_id: str, timeout: Optional[float] = None,
                      stop_on_completion: bool = True) -> Tuple[WildlandResult, List[SyncApiEvent]]:
        """
        Wait until a sync job is completed (state: SYNCED or ERROR).
        :param container_id: container_id in the format as in Wildland Core API.
        :param timeout: optional timeout in seconds.
        :param stop_on_completion: stop the sync job once it reaches SYNCED status
                                   (mostly useful for one-shot jobs).
        :return: WildlandResult and sync errors/conflicts encountered during sync, if any.

        Note: continuous sync can reach state: SYNCED multiple times if there are any storage
              changes detected after it's SYNCED for the first time.
        """
