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
Linux implementation of the Wildland sync API.
"""
import pickle
import select
import sys
import threading
import time
from pathlib import PurePosixPath
from queue import Empty
from socket import socket, SHUT_RDWR, AF_UNIX
from subprocess import Popen
from typing import Optional, Any

from wildland.client import Client
from wildland.core.sync_api import WildlandSync, SyncApiEvent
from wildland.core.sync_internal import POLL_TIMEOUT, WlSyncCommandType
from wildland.core.wildland_result import wildland_result, WLErrorType, WildlandResult
from wildland.log import get_logger, init_logging
from wildland.storage_sync.base import SyncEvent

logger = get_logger('sync-api-linux')


class WildlandSyncLinux(WildlandSync):
    """
    Linux implementation of the sync API.
    """

    def __init__(self, client: Client):
        super().__init__(client)
        self.socket_path = self.client.config.get('sync-socket-path')
        self.manager: Optional[socket] = None
        self.manager_thread: Optional[threading.Thread] = None
        self.event_thread: Optional[threading.Thread] = None

    @staticmethod
    def _recv_msg(sock: socket) -> Any:
        """
        Receives a message from socket (assumes data is available).
        """
        try:
            data = sock.recv(1024)
        except OSError:  # disconnected etc
            return None

        if len(data) == 0:
            return None

        return pickle.loads(data)

    def _manager_thread(self, conn: socket):
        """
        Communicates with the manager: sends commands, receives replies/events.
        """
        threading.current_thread().name = 'manager'
        logger.debug('manager thread started')
        while self.manager:
            try:
                try:
                    with self.requests_lock:
                        cmd_id = self.to_send.get(timeout=POLL_TIMEOUT)
                        request = self.requests[cmd_id]
                        conn.sendall(pickle.dumps(request.cmd))

                        # special case: we don't expect a response for this command
                        # response can arrive sometimes, but will be ignored
                        if request.cmd.type == WlSyncCommandType.SHUTDOWN:
                            request.response = WildlandResult.OK(), None
                            request.ready.set()
                except Empty:
                    # nothing to send, check if there's data to receive
                    rl, _, _ = select.select([conn], [], [], POLL_TIMEOUT)
                    if len(rl) == 0:
                        continue

                    msg = self._recv_msg(conn)
                    if msg is None:
                        continue

                    assert isinstance(msg, tuple), 'Invalid message from manager'

                    if isinstance(msg[1], SyncEvent):
                        # (handler_id, event)
                        self.event_queue.put((msg[0], SyncApiEvent.from_raw(msg[1])))
                    else:
                        # reply for some request: (cmd_id, (WildlandResult, data))
                        cmd_id = msg[0]
                        with self.requests_lock:
                            assert isinstance(msg[1], tuple), 'Invalid message from manager'
                            if cmd_id in self.requests.keys():
                                logger.debug('completing request %d', cmd_id)
                                request = self.requests[cmd_id]
                                request.response = msg[1]
                                request.ready.set()
                            else:
                                logger.warning('Unexpected response from manager: cmd %d -> %s',
                                               cmd_id, msg[1])
            except (OSError, ValueError):
                logger.info('manager disconnected')
                break
            except Exception:
                logger.exception('manager thread:')
                break

        try:
            conn.shutdown(SHUT_RDWR)
        except (OSError, ValueError):  # already disconnected
            pass

        conn.close()
        logger.debug('manager thread finished')

    def _event_thread(self):
        """
        Dispatch queued events to registered callbacks.
        """
        threading.current_thread().name = 'events'
        logger.debug('event thread started')
        while self.manager:
            try:
                handler_id, event = self.event_queue.get(timeout=POLL_TIMEOUT)
                with self.event_lock:
                    if handler_id in self.event_callbacks.keys():
                        self.event_callbacks[handler_id](event)
                    else:
                        logger.warning('Dispatching event %s for missing callback %d',
                                       event, handler_id)
            except Empty:
                continue

        logger.debug('event thread finished')

    def _connect_manager(self, wait: bool = True) -> Optional[socket]:
        """
        Try connecting to the sync manager.
        :param wait: whether to wait until the socket accepts connections.
        :return: communication socket if successful, otherwise None.
        """
        logger.debug('connecting to manager socket')
        sock = socket(family=AF_UNIX)
        sock.setblocking(False)
        for i in range(5):
            try:
                sock.connect(self.socket_path)
                return sock
            except (ConnectionRefusedError, FileNotFoundError):
                if wait:
                    time.sleep(1)
                    continue
                break

        logger.info('failed to connect to manager socket')
        return None

    @wildland_result()
    def syncer_start(self) -> WildlandResult:
        if self.manager:
            return WildlandResult.OK()

        logger.info('initializing manager')
        conn = self._connect_manager(wait=False)
        if not conn:
            cmd = [sys.executable, '-m', 'wildland.core.linux.sync_manager',
                   '-b', str(self.client.base_dir), '-l', '-']  # TODO remove console log
            logger.debug('Starting sync manager: %s', cmd)
            Popen(cmd)
            conn = self._connect_manager(wait=True)

        if not conn:
            logger.warning('Failed to connect to sync manager')
            return WildlandResult.error(WLErrorType.SYNC_FAILED_TO_COMMUNICATE_WITH_MANAGER)

        self.manager = conn

        self.event_thread = threading.Thread(target=self._event_thread)
        self.event_thread.start()

        self.manager_thread = threading.Thread(target=self._manager_thread, args=(conn,))
        self.manager_thread.start()

        logger.info('manager initialized')
        return WildlandResult.OK()

    def syncer_stop(self) -> WildlandResult:
        if not self.manager:
            return WildlandResult.OK()

        logger.info('stopping manager')
        cmd = self._new_cmd(WlSyncCommandType.SHUTDOWN)
        result, _ = self._execute_cmd(cmd)
        self.manager.close()
        self.manager = None

        logger.debug('waiting for manager thread')
        assert self.manager_thread
        self.manager_thread.join()
        self.manager_thread = None

        logger.debug('waiting for event thread')
        assert self.event_thread
        self.event_thread.join()
        self.event_thread = None
        logger.info('manager stopped')
        return result


# TODO this is just a quick test
import click

from pathlib import Path
from wildland.core.core_utils import parse_wl_storage_id

BASE_DIR = PurePosixPath('/home/user/.config/wildland')
client = Client(base_dir=BASE_DIR)


def api_client(num: int):
    logger.info(f'{num} api start')
    api = WildlandSyncLinux(client)
    ret = api.syncer_start()
    logger.info(f'{num} start = %s', ret)

    ret = api.pause_container_sync(str(num))
    logger.info(f'{num} pause = %s', ret.errors[0].diagnostic_info)


def multi_test():
    threads = []
    logger.info('API starting threads')
    for i in range(5):
        thread = threading.Thread(target=api_client, args=(i,))
        threads.append(thread)
        thread.start()

    logger.info('API waiting')
    for thread in threads:
        thread.join()


def callback(event: SyncApiEvent):
    logger.info('API event: %s', event)


@click.command()
@click.option('--s1', help='first storage ID', required=True)
@click.option('--s2', help='second storage ID', required=True)
def main(s1: str, s2: str):
    api = WildlandSyncLinux(client)

    ret = api.syncer_start()
    logger.info('main: start = %s', ret)

    _, cont, _ = parse_wl_storage_id(s1)
    logger.info(f's1 {s1}, cont {cont}')

    ret = api.start_container_sync(cont, s1, s2, True, False)
    logger.info('main: sync = %s', ret)

    ret = api.register_event_handler(cont, set(), callback)
    logger.info('main: register = %s', ret)
    Path('/home/user/storage/s1/testfile').touch()

    time.sleep(5)

    ret = api.syncer_stop()
    logger.info('main: stop = %s', ret)


if __name__ == '__main__':
    init_logging(console=True)
    main()
