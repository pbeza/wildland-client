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
Public API for Wildland sync operations.
"""
import abc
import threading
from dataclasses import dataclass
from queue import Queue
from typing import Any, List, Dict, Tuple, Optional, Callable, Set

from wildland.client import Client
from wildland.core.core_utils import parse_wl_storage_id
from wildland.core.sync_internal import WlSyncCommand, WlSyncCommandType
from wildland.core.sync_types import SyncApiEvent, SyncApiEventType, SyncApiFileState
from wildland.core.wildland_result import WildlandResult, WLErrorType, wildland_result
from wildland.log import get_logger
from wildland.storage_sync.base import SyncState, SyncConflict

logger = get_logger('sync-api')


class WildlandSync(metaclass=abc.ABCMeta):
    """
    Base class for the sync API. Acts as a client sending commands to a sync manager.
    """
    @dataclass
    class Request:
        """
        Encapsulates a single client request that should have a response.
        """
        cmd: WlSyncCommand
        ready: threading.Event
        response: Optional[Tuple[WildlandResult, Any]] = None

    def __init__(self, client: Client):
        self.cmd_id: int = 0
        self.client = client

        # Requests that await processing.
        # Subclass implementations should asynchronously send requests with IDs in self.to_send
        # to manager, and fill in the Request.response field with data received from manager.
        self.requests: Dict[int, WildlandSync.Request] = dict()  # cmd_id -> Request
        self.requests_lock = threading.Lock()

        # cmd_id from requests that await processing.
        # Corresponding requests should be asynchronously sent to manager by subclass
        # implementations.
        self.to_send: Queue[int] = Queue()

        # Events to dispatch to callbacks (handler_id, SyncApiEvent).
        # Should be asynchronously populated by subclass implementations.
        self.event_queue: Queue[Tuple[int, SyncApiEvent]] = Queue()

        # Subclass implementations should asynchronously dispatch events from
        # self.event_queue to these callbacks.
        self.event_callbacks: Dict[int, Callable] = dict()  # handler_id -> callback
        self.event_lock = threading.Lock()

    def _new_cmd(self, cmd: WlSyncCommandType, **kwargs) -> WlSyncCommand:
        """
        Create a WlSyncCommand with instance-unique ID.
        """
        self.cmd_id += 1
        return WlSyncCommand.from_args(self.cmd_id, cmd, **kwargs)

    def _execute_cmd(self, cmd: WlSyncCommand) -> Tuple[WildlandResult, Any]:
        """
        Execute a WlSyncCommand (send command to the manager and return the reply).
        :return: Tuple containing WildlandResult showing if the command was successful,
                 and data returned by the command handler (can be None).
        """
        request = WildlandSync.Request(cmd, threading.Event())

        logger.debug('executing %s', cmd)
        with self.requests_lock:
            self.requests[cmd.id] = request
            self.to_send.put(cmd.id)

        logger.debug('waiting for %d', request.cmd.id)
        request.ready.wait()

        assert request.response is not None

        logger.debug('executed %d', request.cmd.id)
        with self.requests_lock:
            self.requests.pop(cmd.id)

        return request.response

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

    @wildland_result()
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
        """
        user1_id, container1_uuid, backend1_uuid = parse_wl_storage_id(source_storage_id)
        user2_id, container2_uuid, backend2_uuid = parse_wl_storage_id(target_storage_id)

        assert user1_id == user2_id, 'Trying to sync between storages of different users'
        assert container1_uuid == container2_uuid, \
            'Trying to sync between storages of different containers'

        try:
            container = next(self.client.load_containers_from(f'{user1_id}:{container1_uuid}:'))
        except StopIteration:
            return WildlandResult.error(WLErrorType.CONTAINER_NOT_FOUND, offender_id=container_id)

        logger.debug('container: %s, storages %s/%s, cont %s, uni %s', container, backend1_uuid,
                     backend2_uuid, continuous, unidirectional)

        source = self.client.get_local_storage(container, backend1_uuid)
        target = self.client.get_remote_storage(container, backend2_uuid)

        cmd = self._new_cmd(WlSyncCommandType.JOB_START,
                            container_id=container_id,
                            source_params=source.params,
                            target_params=target.params,
                            continuous=continuous,
                            unidirectional=unidirectional)
        result, _ = self._execute_cmd(cmd)  # this command only returns success status
        return result

    def stop_container_sync(self, container_id: str, force: bool) -> WildlandResult:
        """
        Stop syncing given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :param force: should stop be immediate or wait until the end of current syncing operation.
        :return: WildlandResult showing if it was successful.
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_STOP,
                            container_id=container_id,
                            force=force)
        result, _ = self._execute_cmd(cmd)
        return result

    def pause_container_sync(self, container_id: str) -> WildlandResult:
        """
        Pause syncing given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult showing if it was successful.
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_PAUSE,
                            container_id=container_id)
        result, _ = self._execute_cmd(cmd)
        return result

    def resume_container_sync(self, container_id: str) -> WildlandResult:
        """
        Resume syncing given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult showing if it was successful.
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_RESUME,
                            container_id=container_id)
        result, _ = self._execute_cmd(cmd)
        return result

    def register_event_handler(self, container_id: Optional[str], filters: Set[SyncApiEventType],
                               callback: Callable[[SyncApiEvent], None]) \
            -> Tuple[WildlandResult, Optional[int]]:
        """
        Register handler for events; only receives events listed in filters.
        :param container_id: Container for which to receive events, all containers if None
        :param filters: Set of event types to be given to handler (empty means all)
        :param callback: function that takes SyncApiEvent as param and returns nothing
        :return: Tuple of WildlandResult and id of the registered handler (if register
                 was successful)
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_SET_CALLBACK,
                            container_id=container_id,
                            filters=filters)

        result, handler_id = self._execute_cmd(cmd)
        if not result.success:
            return result, None

        with self.event_lock:
            self.event_callbacks[handler_id] = callback

        return result, handler_id

    def remove_event_handler(self, handler_id: int) -> WildlandResult:
        """
        De-register event handler with the provided id.
        :param handler_id: value returned by register_event_handler
        :return: WildlandResult showing if it was successful.
        """
        with self.event_lock:
            if handler_id not in self.event_callbacks.keys():
                return WildlandResult.error(WLErrorType.SYNC_CALLBACK_NOT_FOUND,
                                            diagnostic_info=str(handler_id))

        cmd = self._new_cmd(WlSyncCommandType.JOB_CLEAR_CALLBACK,
                            callback_id=handler_id)
        result, _ = self._execute_cmd(cmd)
        if not result.success:
            return result

        with self.event_lock:
            self.event_callbacks.pop(handler_id)

        return WildlandResult.OK()

    def get_container_sync_state(self, container_id: str) -> \
            Tuple[WildlandResult, Optional[SyncState]]:
        """
        Get current state of sync of the given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult and overall state of the sync.
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_STATE,
                            container_id=container_id)
        result, state = self._execute_cmd(cmd)
        return result, state

    def get_container_sync_details(self, container_id: str) -> \
            Tuple[WildlandResult, List[SyncApiFileState]]:
        """
        Get current sync state of all files in the given container.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult and a list with states of all container files.
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_DETAILS,
                            container_id=container_id)
        result, data = self._execute_cmd(cmd)
        # TODO
        return result, data

    def get_container_sync_conflicts(self, container_id: str) -> \
            Tuple[WildlandResult, List[SyncConflict]]:
        """
        Get list of conflicts in given container's sync.
        :param container_id: container_id in the format as in Wildland Core API.
        :return: WildlandResult and list of file conflicts.
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_DETAILS,
                            container_id=container_id)
        result, data = self._execute_cmd(cmd)
        # TODO: process result and extract conflicts
        return result, data

    def get_file_sync_state(self, container_id: str, path: str) -> \
            Tuple[WildlandResult, Optional[SyncApiFileState]]:
        """
        Get sync state of a given file.
        :param container_id: container_id in the format as in Wildland Core API.
        :param path: path to file in the container
        :return: WildlandResult and file state
        """
        cmd = self._new_cmd(WlSyncCommandType.JOB_FILE_DETAILS,
                            container_id=container_id,
                            path=path)
        result, state = self._execute_cmd(cmd)
        return result, state

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
        cmd = self._new_cmd(WlSyncCommandType.FORCE_FILE,
                            container_id=container_id,
                            path=path,
                            source_storage_id=source_storage_id,
                            target_storage_id=target_storage_id)
        result, _ = self._execute_cmd(cmd)
        return result
