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
Linux implementation of sync manager.
"""
import ctypes
import inspect
import os
import signal
import threading
from dataclasses import dataclass
from functools import partial
from multiprocessing.connection import Listener, Connection
from pathlib import Path
from queue import Empty, Queue
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

        self.listener: Optional[Listener] = None
        self.listener_thread: Optional[threading.Thread] = None

        config = Config.load(base_dir)
        self.socket_path = config.get('sync-socket-path')
        Path(self.socket_path).unlink(missing_ok=True)
        logger.debug(f'sock: {self.socket_path}')

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

    def _client_thread(self, client_id: int, conn: Connection):
        """
        Communicates with a single client.
        """
        threading.current_thread().name = 'client'
        logger.debug('client %d thread started', client_id)

        responses: Queue[Tuple[int, Any]] = Queue()
        with self.responses_lock:
            self.responses[client_id] = responses

        while self.active:
            try:
                try:
                    msg = responses.get(timeout=POLL_TIMEOUT)
                    conn.send(msg)
                except Empty:
                    # nothing to send, try receiving commands
                    if conn.poll(timeout=POLL_TIMEOUT):
                        cmd = conn.recv()
                        logger.debug('client %d: got %s', client_id, cmd)
                        self.requests.put(WlSyncManager.Request(client_id, cmd))
            except Exception:
                logger.exception('client %d thread:', client_id)
                break

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
                # no way to interrupt accept(): https: // bugs.python.org / issue32244
                conn = self.listener.accept()
                client_id = self.new_client_id()
                logger.debug('connection accepted from %s, id %d',
                             self.listener.last_accepted, client_id)
                worker = threading.Thread(target=self._client_thread, args=(client_id, conn))
                worker.start()
                # client threads will exit on stop()
            except Exception:
                logger.exception('listener thread:')

        logger.debug('listener thread finished')

    @wildland_result()
    def start(self) -> WildlandResult:
        logger.info('starting')
        if self.active:
            return WildlandResult.error(error_code=WLErrorType.SYNC_MANAGER_ALREADY_ACTIVE,
                                        error_description="Sync manager already active")

        self.listener = Listener(family='AF_UNIX', address=self.socket_path)
        self.active = True
        self.listener_thread = threading.Thread(target=self._listener_thread)
        self.listener_thread.start()
        logger.info('start ok')
        return WildlandResult.OK()

    @wildland_result()
    def stop(self) -> WildlandResult:
        logger.info('stopping')
        if not self.active:
            return WildlandResult.error(error_code=WLErrorType.SYNC_MANAGER_NOT_ACTIVE,
                                        error_description="Sync manager not active")
        self.active = False
        assert self.listener
        self.listener.close()  # TODO aborts the listener thread if in the middle of accept() call
        # assert self.listener_thread
        # self.listener_thread.join()
        self.listener_thread._stop()
        self.listener_thread = None
        self.listener = None

        for job in self.jobs.values():
            job.stop_event.set()
            assert isinstance(job, WlSyncManagerLinux.SyncJobLinux)
            assert job.thread
            job.thread.join()

        with self.jobs_lock:
            self.jobs.clear()

        logger.info('stop ok')
        return WildlandResult.OK()

    @WlSyncCommand.handler(WlSyncCommandType.JOB_START)
    def cmd_job_start(self, container_id: str, source_storage_id: str, target_storage_id: str,
                      continuous: bool, unidirectional: bool) \
            -> Tuple[WildlandResult, None]:
        logger.debug('cmd_job_start: %s %s %s %s %s', container_id, continuous, unidirectional,
                     source_storage_id, target_storage_id)

        if not self.active:
            return WildlandResult.error(error_code=WLErrorType.SYNC_MANAGER_NOT_ACTIVE,
                                        error_description="Sync manager not active",
                                        diagnostic_info=container_id), None

        with self.jobs_lock:
            if container_id in self.jobs.keys():
                return WildlandResult.error(error_code=WLErrorType.SYNC_FOR_CONTAINER_ALREADY_RUNNING,
                                            error_description="Sync already running for this container",
                                            diagnostic_info=container_id), None

            job = WlSyncManagerLinux.SyncJobLinux()
            job.thread = threading.Thread(target=self._job_worker,
                                          args=(container_id, source_storage_id, target_storage_id,
                                                continuous, unidirectional,
                                                partial(self._event_handler, container_id),
                                                job.stop_event))

            self.jobs[container_id] = job
            job.thread.start()
            return WildlandResult.OK(), None

    @WlSyncCommand.handler(WlSyncCommandType.JOB_STOP)
    def cmd_job_stop(self, container_id: str, force: bool) -> Tuple[WildlandResult, None]:
        logger.debug('cmd_job_stop: %s %s', container_id, force)
        if not self.active:
            return WildlandResult.error(error_code=WLErrorType.SYNC_MANAGER_NOT_ACTIVE,
                                        error_description="Sync manager not active",
                                        diagnostic_info=container_id), None

        # TODO review locking
        with self.jobs_lock:
            try:
                job = self.jobs[container_id]
                job.stop_event.set()
                # TODO force
                assert isinstance(job, WlSyncManagerLinux.SyncJobLinux)
                assert job.thread
                job.thread.join()
                self.jobs.pop(container_id)
                return WildlandResult.OK(), None
            except KeyError:
                return WildlandResult.error(error_code=WLErrorType.SYNC_FOR_CONTAINER_NOT_RUNNING,
                                            error_description="Sync not running for this container",
                                            diagnostic_info=container_id), None


@click.command()
@click.option('-b', '--base-dir', help='base directory for configuration', required=True)
@click.option('-l', '--log-path', help=f'path to log file (default: {DEFAULT_LOG_PATH}),\n'
                                       f'can be set in {LOG_ENV_NAME} environment variable')
def main(base_dir: str, log_path: str):
    """
    Module entry point.
    """
    print(f'log: {log_path}, base: {base_dir}')

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
    manager.start()
    manager.main()
    print('END')


# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
