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
Linux implementation of sync manager.
"""
import os
import pickle
import select
import signal
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from queue import Queue
from socket import socket, AF_UNIX, SHUT_RDWR
from typing import Optional, Tuple, Any

import click

from wildland.config import Config
from wildland.core.sync_internal import POLL_TIMEOUT, WlSyncCommandType, WlSyncCommand
from wildland.core.wildland_result import WLErrorType, wildland_result, WildlandResult
from wildland.core.sync_manager import WlSyncManager
from wildland.log import get_logger, init_logging

logger = get_logger('sync-manager-linux')

LOG_ENV_NAME = 'WL_SYNC_LOG_PATH'  # environmental variable with log path override
DEFAULT_LOG_PATH = f"{os.path.expanduser('~')}/.local/share/wildland/wl-sync.log"


class WlSyncManagerLinux(WlSyncManager):
    """
    Linux implementation of the sync manager (threaded daemon listening on a UNIX socket).
    """

    @dataclass
    class SyncJobLinux(WlSyncManager.SyncJob):
        """
        Data about a running sync job.
        """
        thread: Optional[threading.Thread] = None

    def __init__(self, base_dir: str):
        super().__init__()

        self.listener: Optional[socket] = None
        self.listener_thread: Optional[threading.Thread] = None

        config = Config.load(base_dir)
        self.socket_path = config.get('sync-socket-path')

        logger.debug(f'socket: {self.socket_path}')

        signal.signal(signal.SIGINT, self.sighandler)
        signal.signal(signal.SIGTERM, self.sighandler)
        logger.debug('init ok')

    def sighandler(self, signum: int, _frame):
        """
        Stops the daemon upon SIGINT/SIGTERM.
        """
        logger.debug('signal received: %d', signum)
        if signum in (signal.SIGINT, signal.SIGTERM):
            logger.info('manager stopping because of signal')
            self.stop()

    def can_run(self):
        """
        Returns True if no other instance of the manager is running.
        """
        if Path(self.socket_path).exists():
            return False

        return True

    @staticmethod
    def _recv_msg(sock: socket) -> Any:
        """
        Receives a message from socket (assumes data is available).
        """
        data = sock.recv(1024)
        if len(data) == 0:
            raise BrokenPipeError

        return pickle.loads(data)

    def __try_recv(self, conn: socket, client_id: int):
        """
        Try receiving messages from a client.
        """
        rl, _, _ = select.select([conn], [], [], POLL_TIMEOUT)
        if len(rl) == 0:
            return

        cmd = self._recv_msg(conn)
        if cmd is not None:
            self.requests.put(WlSyncManager.Request(client_id, cmd))

    @staticmethod
    def __try_send(conn: socket, responses: Queue):
        """
        Try sending queued messages to a client.
        """
        if responses.empty():
            return

        msg = responses.get(timeout=POLL_TIMEOUT)
        if msg is not None:
            x = pickle.dumps(msg)
            conn.sendall(x)

    def _client_thread(self, client_id: int, conn: socket):
        """
        Communicates with a single client.
        """
        threading.current_thread().name = f'client {client_id}'
        logger.debug('client %d thread started', client_id)

        responses: Queue[Tuple[int, Any]] = Queue()
        with self.responses_lock:
            self.responses[client_id] = responses

        while self.active:
            try:
                self.__try_recv(conn, client_id)
                self.__try_send(conn, responses)
            except (OSError, ValueError, BrokenPipeError):
                logger.info('disconnected')
                break
            except Exception:
                logger.exception('client %d thread:', client_id)
                break

        conn.shutdown(SHUT_RDWR)
        conn.close()
        with self.responses_lock:
            self.responses[client_id] = None

        logger.debug('client %d thread finished', client_id)

    def _listener_thread(self):
        """
        Thread that accepts client connections and spawns client threads.
        """
        threading.current_thread().name = 'listener'
        assert self.listener
        logger.debug('listener thread started')
        while self.active:
            try:
                # select with timeout so it's interruptible
                rl, _, _ = select.select([self.listener], [], [], 1)
                if len(rl) == 0:
                    continue

                conn, _ = self.listener.accept()
                client_id = self.new_client_id()
                logger.debug('connection accepted, id %d', client_id)
                worker = threading.Thread(target=self._client_thread, args=(client_id, conn))
                worker.start()
                # client threads will exit on stop()
            except OSError as ex:
                logger.info('listener aborted: %s', ex)
                break
            except Exception:
                logger.exception('listener thread exception:')
                break

        logger.debug('listener thread finished')

    @wildland_result()
    def start(self) -> WildlandResult:
        logger.info('starting')
        if self.active:
            return WildlandResult.error(WLErrorType.SYNC_MANAGER_ALREADY_ACTIVE)

        self.listener = socket(family=AF_UNIX)
        self.listener.setblocking(False)
        self.listener.bind(self.socket_path)
        self.listener.listen()
        self.active = True
        self.listener_thread = threading.Thread(target=self._listener_thread)
        self.listener_thread.start()
        logger.info('start ok')
        return WildlandResult.OK()

    @wildland_result()
    def stop(self) -> WildlandResult:
        logger.info('stopping')
        if not self.active:
            return WildlandResult.error(WLErrorType.SYNC_MANAGER_NOT_ACTIVE)
        self.active = False
        assert self.listener
        self.listener.shutdown(SHUT_RDWR)
        self.listener.close()
        assert self.listener_thread
        logger.debug('waiting for listener thread')
        self.listener_thread.join()
        self.listener_thread = None
        self.listener = None

        logger.debug('stopping jobs')
        for job in self.jobs.values():
            assert job.stop_event
            job.stop_event.set()
            assert isinstance(job, WlSyncManagerLinux.SyncJobLinux)
            assert job.thread
            job.thread.join()

        with self.jobs_lock:
            self.jobs.clear()

        Path(self.socket_path).unlink()
        logger.info('stop ok')
        # TODO clear event handlers?
        return WildlandResult.OK()

    @WlSyncCommand.handler(WlSyncCommandType.JOB_START)
    def cmd_job_start(self, container_id: str, source_params: dict, target_params: dict,
                      continuous: bool, unidirectional: bool) -> WildlandResult:
        logger.debug('cmd_job_start: %s %s %s %s %s', container_id, continuous, unidirectional,
                     source_params, target_params)

        if not self.active:
            return WildlandResult.error(WLErrorType.SYNC_MANAGER_NOT_ACTIVE)

        init_event = threading.Event()
        with self.jobs_lock:
            if container_id in self.jobs.keys():
                return WildlandResult.error(WLErrorType.SYNC_FOR_CONTAINER_ALREADY_RUNNING,
                                            diagnostic_info=container_id)

            job = WlSyncManagerLinux.SyncJobLinux()
            job.thread = threading.Thread(target=self._job_worker,
                                          args=(container_id, source_params, target_params,
                                                continuous, unidirectional,
                                                partial(self._event_handler, container_id),
                                                job.stop_event, init_event))

            self.jobs[container_id] = job
            job.thread.start()

        init_event.wait()  # wait for syncer initialization
        return WildlandResult.OK()

    @WlSyncCommand.handler(WlSyncCommandType.JOB_STOP)
    def cmd_job_stop(self, container_id: str, force: bool) -> WildlandResult:
        logger.debug('cmd_job_stop: %s %s', container_id, force)
        if not self.active:
            return WildlandResult.error(WLErrorType.SYNC_MANAGER_NOT_ACTIVE)

        # TODO review locking
        with self.jobs_lock:
            try:
                job = self.jobs[container_id]
                assert job.stop_event
                job.stop_event.set()
                # TODO force
                assert isinstance(job, WlSyncManagerLinux.SyncJobLinux)
                assert job.thread
                job.thread.join()
                self.jobs.pop(container_id)
                return WildlandResult.OK()
            except KeyError:
                return WildlandResult.error(WLErrorType.SYNC_FOR_CONTAINER_NOT_RUNNING,
                                            offender_id=str(container_id))


@click.command()
@click.option('-b', '--base-dir', help='base directory for configuration', required=True)
@click.option('-l', '--log-path', help=f'path to log file (default: {DEFAULT_LOG_PATH}),\n'
                                       f'can be set in {LOG_ENV_NAME} environment variable')
def main(base_dir: str, log_path: str):
    """
    Module entry point.
    """
    if not log_path:
        if LOG_ENV_NAME in os.environ:
            log_path = os.environ[LOG_ENV_NAME]
        else:
            log_path = DEFAULT_LOG_PATH

    if log_path == '-':
        init_logging(console=True)
    else:
        init_logging(console=False, file_path=log_path)

    manager = WlSyncManagerLinux(base_dir)
    if not manager.can_run():
        logger.warning('another instance running, exiting')
        return

    manager.start()
    logger.debug('enter main')
    x = manager.main()
    logger.debug('END: %s', x)
    if not x.success:
        logger.warning('error: %s', x.errors[0])


# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
