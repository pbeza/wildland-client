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
from wildland.core.wildland_sync_api import SyncApiEventType
from wildland.log import get_logger, init_logging
from wildland.storage_sync.base import SyncEvent, SyncState

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
        data = sock.recv(1024)
        if len(data) == 0:
            raise BrokenPipeError

        return pickle.loads(data)

    def __try_recv(self, conn: socket):
        """
        Try receiving messages from the manager.
        """
        ready, _, _ = select.select([conn], [], [], POLL_TIMEOUT)
        if len(ready) == 0:
            return

        msg = self._recv_msg(conn)

        assert isinstance(msg, tuple), f'Invalid message from manager: {msg}'

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

    def __try_send(self, conn: socket):
        """
        Try sending queued messages to the manager.
        """
        with self.requests_lock:
            if self.to_send.empty():
                return

            cmd_id = self.to_send.get()
            request = self.requests[cmd_id]
            conn.sendall(pickle.dumps(request.cmd))

            # special case: we don't expect a response for this command
            # response can arrive sometimes, but will be ignored
            if request.cmd.type == WlSyncCommandType.SHUTDOWN:
                request.response = WildlandResult.OK(), None
                request.ready.set()

    def _manager_thread(self):
        """
        Communicates with the manager: sends commands, receives replies/events.
        """
        threading.current_thread().name = 'manager'
        logger.debug('manager thread started')
        while self.manager:
            try:
                self.__try_recv(self.manager)
                self.__try_send(self.manager)
            except (OSError, ValueError, BrokenPipeError):
                logger.debug('manager disconnected')
                break
            except Exception:
                logger.exception('manager thread:')
                break

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

        logger.debug('failed to connect to manager socket')
        return None

    @wildland_result()
    def syncer_start(self) -> WildlandResult:
        if self.manager:
            return WildlandResult.OK()

        logger.debug('initializing sync manager')
        conn = self._connect_manager(wait=False)
        if not conn:
            cmd = [sys.executable, '-m', 'wildland.core.linux.sync_manager',
                   '-b', str(self.client.base_dir)]
            logger.debug('Starting sync manager: %s', cmd)
            Popen(cmd)
            conn = self._connect_manager(wait=True)

        if not conn:
            logger.warning('Failed to connect to sync manager')
            return WildlandResult.error(WLErrorType.SYNC_FAILED_TO_COMMUNICATE_WITH_MANAGER)

        conn.close()

        logger.debug('sync manager initialized')
        return WildlandResult.OK()

    def syncer_stop(self) -> WildlandResult:
        if self.manager is None:
            return WildlandResult.OK()

        logger.debug('stopping sync manager')
        cmd = self._new_cmd(WlSyncCommandType.SHUTDOWN)
        result, _ = self._execute_cmd(cmd)

        self.detach()

        # since we don't expect a reply for this command, manually make sure the manager is stopped
        # to not create any race conditions
        while Path(self.socket_path).exists():
            # TODO timeout and kill
            time.sleep(0.01)

        logger.debug('sync manager stopped')
        return result

    def attach(self) -> WildlandResult:
        if self.manager:
            return WildlandResult.OK()

        if not self.syncer_start().success:
            logger.warning('Failed to connect to sync manager')
            return WildlandResult.error(WLErrorType.SYNC_FAILED_TO_COMMUNICATE_WITH_MANAGER)

        self.manager = self._connect_manager(wait=False)
        if not self.manager:
            logger.warning('Failed to connect to sync manager')
            return WildlandResult.error(WLErrorType.SYNC_FAILED_TO_COMMUNICATE_WITH_MANAGER)

        self.event_thread = threading.Thread(target=self._event_thread)
        self.event_thread.start()

        self.manager_thread = threading.Thread(target=self._manager_thread)
        self.manager_thread.start()
        return WildlandResult.OK()

    def detach(self) -> WildlandResult:
        if self.manager is None:
            return WildlandResult.OK()

        self.manager.shutdown(SHUT_RDWR)
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

        return WildlandResult.OK()


# TODO this is just a quick test
import click
import shutil
import typing

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
@typing.no_type_check  # `status` variable has different types between calls
def main(s1: str, s2: str):
    api = WildlandSyncLinux(client)

    status = api.attach()
    logger.info('main: attach = %s', status)

    _, cont, _ = parse_wl_storage_id(s1)

    status, handler_id = api.register_event_handler(cont, {SyncApiEventType.STATE,
                                                           SyncApiEventType.PROGRESS,
                                                           SyncApiEventType.CONFLICT}, callback)
    logger.info('main: register = %s, %d', status, handler_id)

    Path('/home/user/storage/s1/subdir').mkdir(parents=True, exist_ok=True)
    Path('/home/user/storage/s1/subdir/f1').touch()
    Path('/home/user/storage/s1/subdir/f2').touch()
    Path('/home/user/storage/s1/subdir/f3').touch()
    shutil.rmtree('/home/user/storage/s2/subdir', ignore_errors=True)
    Path('/home/user/storage/s1/conf1').write_bytes(b'conflict 1')
    Path('/home/user/storage/s2/conf1').write_bytes(b'conflict 2')

    status = api.start_container_sync(cont, s1, s2, True, False)
    logger.info('main: sync = %s', status)

    status = api.get_file_sync_state(cont, 'testfile')
    logger.info(f'main: file sync state = {status}')

    logger.info('main: wait for stop')
    status = api.wait_for_sync(cont, 10)
    logger.info(f'main: wait1 = {status}')

    status = api.get_container_sync_conflicts(cont)
    logger.info(f'main: conflicts = {status}')

    time.sleep(1)
    Path('/home/user/storage/s1/testfile').touch()
    status = api.wait_for_sync(cont, 10)
    logger.info(f'main: wait2 = {status}')

    status = api.get_current_sync_jobs()
    logger.info(f'main: all jobs = {status}')

    status = api.get_file_sync_state(cont, 'testfile')
    logger.info(f'main: file info = {status}')

    status = api.get_container_sync_details(cont)
    logger.info(f'main: details = {status}')

    status = api.remove_event_handler(handler_id)
    logger.info(f'main: remove handler = {status}')

    Path('/home/user/storage/s1/testfile').write_bytes(b'test')

    status = api.detach()
    logger.info('main: detach = %s', status)

    status = api.attach()
    logger.info('main: attach = %s', status)

    status = api.syncer_stop()
    logger.info('main: stop = %s', status)

    Path('/home/user/storage/s1/testfile').unlink()
    shutil.rmtree('/home/user/storage/s1/subdir')
    Path('/home/user/storage/s2/testfile').unlink()
    Path('/home/user/storage/s2/x').unlink()
    shutil.rmtree('/home/user/storage/s2/subdir')
    Path('/home/user/storage/s1/conf1').unlink()
    Path('/home/user/storage/s2/conf1').unlink()


if __name__ == '__main__':
    init_logging(console=True)
    main()
