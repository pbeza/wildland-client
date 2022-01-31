# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
Linux implementation of the Wildland sync API.
"""
import sys
import threading
import time
from multiprocessing.connection import Connection, Client
from pathlib import PurePosixPath
from queue import Empty
from subprocess import Popen
from typing import Optional

from wildland.config import Config
from wildland.core.sync_api import WildlandSync, SyncApiEvent
from wildland.core.sync_internal import POLL_TIMEOUT, WlSyncCommandType
from wildland.core.wildland_result import wildland_result, WLErrorType, WildlandResult
from wildland.log import get_logger
from wildland.storage_sync.base import SyncEvent

logger = get_logger('sync-api-linux')


class WildlandSyncLinux(WildlandSync):
    """
    Linux implementation of the sync API.
    """

    def __init__(self, base_dir: PurePosixPath):
        super().__init__()
        config = Config.load(base_dir)
        self.socket_path = config.get('sync-socket-path')
        self.manager: Optional[Connection] = None
        self.manager_thread: Optional[threading.Thread] = None
        self.event_thread: Optional[threading.Thread] = None

    def _manager_thread(self, conn: Connection):
        """
        Communicates with the manager: sends commands, receives replies/events.
        """
        threading.current_thread().name = 'manager'
        logger.debug('manager thread started')
        while self.manager:
            try:
                try:
                    cmd_id = self.to_send.get(timeout=POLL_TIMEOUT)
                    with self.requests_lock:
                        request = self.requests[cmd_id]
                        conn.send(request.cmd)
                except Empty:
                    # nothing to send, check if there's data to receive
                    if conn.poll(timeout=POLL_TIMEOUT):
                        msg = conn.recv()
                        assert isinstance(msg, tuple), 'Invalid message from manager'

                        if isinstance(msg[1], SyncEvent):
                            # (handler_id, event)
                            self.event_queue.put((msg[0], SyncApiEvent.from_raw(msg[1])))
                        else:
                            # reply for some request: (cmd_id, data)
                            cmd_id = msg[0]
                            with self.requests_lock:
                                if cmd_id in self.requests.keys():
                                    request = self.requests[cmd_id]
                                    request.response = msg[1]
                                    request.ready.set()
                                else:
                                    logger.warning('Unexpected response from manager: cmd %d -> %s',
                                                   cmd_id, msg[1])
            except Exception:
                logger.exception('manager thread:')
                break

        conn.close()  # TODO can fail?
        logger.debug('manager thread finished')

    def _event_thread(self):
        """
        Dispatch queued events to registered callbacks.
        """
        threading.current_thread().name = 'events'
        logger.debug('event thread started')
        while self.manager:
            # TODO poll and wait for stop signal
            handler_id, event = self.event_queue.get()
            with self.event_lock:
                if handler_id in self.event_callbacks.keys():
                    self.event_callbacks[handler_id](event)
                else:
                    logger.warning('Dispatching event %s for missing callback %d',
                                   event, handler_id)

        logger.debug('event thread finished')

    def _connect_manager(self) -> Optional[Connection]:
        """
        Try connecting to the sync manager.
        :return: Connection if successful, otherwise None.
        """
        logger.debug('Connecting to manager socket')
        for i in range(5):
            try:
                return Client(family='AF_UNIX', address=self.socket_path)
            except ConnectionRefusedError:
                time.sleep(1)
                pass
            except FileNotFoundError:
                break

        logger.info('Failed to connect to manager socket')
        return None

    @wildland_result
    def syncer_start(self):
        logger.info('initializing manager')
        if self.manager:
            return WildlandResult.OK()

        conn = self._connect_manager()
        if not conn:
            cmd = [sys.executable, '-m', 'wildland.core.wildland_sync_api.manager']  # TODO
            logger.debug('Starting sync manager: %s', cmd)
            Popen(cmd)
            conn = self._connect_manager()

        if not conn:
            logger.warning('Failed to connect to sync manager')
            return WildlandResult.error(error_code=WLErrorType.SYNC_FAILED_TO_COMMUNICATE_WITH_MANAGER,
                                        error_description="Failed to communicate with sync manager")

        self.manager = conn

        self.event_thread = threading.Thread(target=self._event_thread)
        self.event_thread.start()

        self.manager_thread = threading.Thread(target=self._manager_thread, args=(conn,))
        self.manager_thread.start()

        logger.info('manager initialized')
        return WildlandResult.OK()

    @wildland_result
    def syncer_stop(self):
        logger.info('stopping manager')
        if not self.manager:
            return WildlandResult.OK()

        cmd = self._new_cmd(WlSyncCommandType.SHUTDOWN)
        result, _ = self._execute_cmd(cmd)
        self.manager.close()  # TODO this will probably fail since server is already stopped
        self.manager = None
        assert self.manager_thread
        self.manager_thread.join()
        self.manager_thread = None

        # TODO abort event_thread
        assert self.event_thread
        self.event_thread.join()
        self.event_thread = None
        logger.info('manager stopped')
        return result
