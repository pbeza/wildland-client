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
from typing import Any, List, Dict, Tuple, Optional, Callable, Set, Type

import entrypoints

from wildland.client import Client
from wildland.core.core_utils import parse_wl_storage_id
from wildland.core.sync_internal import WlSyncCommand, WlSyncCommandType
from wildland.core.wildland_result import WildlandResult, WLErrorType, wildland_result
from wildland.core.wildland_sync_api import WildlandSyncApi, SyncApiEvent, SyncApiEventType
from wildland.exc import WildlandError
from wildland.log import get_logger
from wildland.storage_sync.base import SyncState, SyncConflict, SyncFileState

logger = get_logger('sync-api')


class WildlandSync(WildlandSyncApi, abc.ABC):
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

    @wildland_result()
    def start_container_sync(self, container_id: str, source_storage_id: str,
                             target_storage_id: str, continuous: bool, unidirectional: bool) \
            -> WildlandResult:
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

    def stop_container_sync(self, container_id: str, force: bool = False) -> WildlandResult:
        cmd = self._new_cmd(WlSyncCommandType.JOB_STOP,
                            container_id=container_id,
                            force=force)
        result, _ = self._execute_cmd(cmd)
        return result

    def pause_container_sync(self, container_id: str) -> WildlandResult:
        cmd = self._new_cmd(WlSyncCommandType.JOB_PAUSE,
                            container_id=container_id)
        result, _ = self._execute_cmd(cmd)
        return result

    def resume_container_sync(self, container_id: str) -> WildlandResult:
        cmd = self._new_cmd(WlSyncCommandType.JOB_RESUME,
                            container_id=container_id)
        result, _ = self._execute_cmd(cmd)
        return result

    def register_event_handler(self, container_id: Optional[str], filters: Set[SyncApiEventType],
                               callback: Callable[[SyncApiEvent], None]) \
            -> Tuple[WildlandResult, int]:
        cmd = self._new_cmd(WlSyncCommandType.JOB_SET_CALLBACK,
                            container_id=container_id,
                            filters=filters)

        result, handler_id = self._execute_cmd(cmd)
        if not result.success:
            return result, 0

        logger.debug('register = %d', handler_id)
        with self.event_lock:
            self.event_callbacks[handler_id] = callback

        return result, handler_id

    def remove_event_handler(self, handler_id: int) -> WildlandResult:
        if handler_id == 0:  # real IDs start with 1, 0 is returned on register failure
            return WildlandResult.OK()

        with self.event_lock:
            if handler_id not in self.event_callbacks.keys():
                return WildlandResult.error(WLErrorType.SYNC_CALLBACK_NOT_FOUND,
                                            offender_id=str(handler_id))

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
        cmd = self._new_cmd(WlSyncCommandType.JOB_STATE,
                            container_id=container_id)
        result, state = self._execute_cmd(cmd)
        return result, state

    def get_container_sync_details(self, container_id: str) -> \
            Tuple[WildlandResult, List[SyncFileState]]:
        cmd = self._new_cmd(WlSyncCommandType.JOB_DETAILS,
                            container_id=container_id)
        result, data = self._execute_cmd(cmd)
        return result, data

    def get_container_sync_conflicts(self, container_id: str) -> \
            Tuple[WildlandResult, List[SyncConflict]]:
        cmd = self._new_cmd(WlSyncCommandType.JOB_CONFLICTS,
                            container_id=container_id)
        result, data = self._execute_cmd(cmd)
        return result, data

    def get_file_sync_state(self, container_id: str, path: str) -> \
            Tuple[WildlandResult, Optional[SyncFileState]]:
        cmd = self._new_cmd(WlSyncCommandType.JOB_FILE_DETAILS,
                            container_id=container_id,
                            path=path)
        result, state = self._execute_cmd(cmd)
        return result, state

    def force_file_sync(self, container_id: str, path: str, source_storage_id: str,
                        target_storage_id: str) -> WildlandResult:
        cmd = self._new_cmd(WlSyncCommandType.FORCE_FILE,
                            container_id=container_id,
                            path=path,
                            source_storage_id=source_storage_id,
                            target_storage_id=target_storage_id)
        result, _ = self._execute_cmd(cmd)
        return result

    def get_current_sync_jobs(self) -> Tuple[WildlandResult, Dict[str, SyncState]]:
        cmd = self._new_cmd(WlSyncCommandType.JOB_LIST)
        result, data = self._execute_cmd(cmd)
        return result, data

    def wait_for_sync(self, container_id: str, timeout: Optional[float] = None,
                      stop_on_completion: bool = True) -> Tuple[WildlandResult, List[SyncApiEvent]]:
        synced = threading.Event()
        events = []

        # we register the callback before checking state manually to avoid a race condition
        # (otherwise state can change after we check it manually but before we register callback)
        def event_callback(event: SyncApiEvent):
            nonlocal events
            if event.type == SyncApiEventType.STATE and event.state == SyncState.SYNCED:
                synced.set()

            # TODO any errors are fatal now, in the future there might be nonfatal ones
            if event.type == SyncApiEventType.ERROR:
                events.append(event)
                synced.set()
                return

        # we don't monitor conflict events, we get them all before returning
        # because there might've been some already before we started waiting
        status, hid = self.register_event_handler(container_id,
                                                  {SyncApiEventType.STATE, SyncApiEventType.ERROR},
                                                  event_callback)
        if not status.success:
            logger.warning('wait_for_sync: failed to register event handler: %s', status)
            return status, events

        try:
            # manually checking state is needed in case the job is already synced
            status, state = self.get_container_sync_state(container_id)
            if not status.success:
                logger.warning('wait_for_sync: failed to get state: %s', status)
                return status, events

            if state == SyncState.SYNCED:
                synced.set()

            if not synced.wait(timeout=timeout):
                return WildlandResult.error(WLErrorType.TIMEOUT), events

            status, conflicts = self.get_container_sync_conflicts(container_id)
            if not status.success:
                logger.warning('wait_for_sync: failed to get conflicts: %s', status)
                return status, events

            for conflict in conflicts:
                events.append(SyncApiEvent(container_id, SyncApiEventType.CONFLICT,
                                           conflict=conflict))

            if stop_on_completion:
                logger.debug('wait_for_sync: stopping job %s', container_id)
                status = self.stop_container_sync(container_id, force=False)  # TODO force
                if not status.success:
                    logger.warning('wait_for_sync: failed to stop job %s: %s', container_id, status)
                    return status, events
        finally:
            self.remove_event_handler(hid)

        return WildlandResult.OK(), events


def sync_api(client: Client) -> WildlandSync:
    """
    Instantiate a sync API implementation.
    """
    for ep in entrypoints.get_group_all('wildland.core.sync_api'):
        try:
            cls: Type[WildlandSync] = ep.load()
            return cls(client)
        except Exception:
            logger.exception('Failed to load API %s', ep)

    logger.error('No sync API implementation found')
    raise WildlandError('No sync API implementation found')
