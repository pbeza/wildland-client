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
Internal API for Wildland sync operations: sync manager.
"""
import abc
import threading
import time
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Callable, Dict, Any, Tuple, Optional, Set

from wildland.core.sync_internal import WlSyncCommand, WlSyncCommandType, POLL_TIMEOUT
from wildland.core.wildland_result import WildlandResult, wildland_result, WLError, WLErrorType
from wildland.core.sync_api import SyncApiFileState, SyncApiEventType
from wildland.log import get_logger
from wildland.storage_backends.base import StorageBackend
from wildland.storage_sync.base import SyncState, BaseSyncer, SyncEvent, SyncErrorEvent, \
    SyncStateEvent

logger = get_logger('sync-manager')


class WlSyncManager(metaclass=abc.ABCMeta):
    """
    Coordinates and hosts all sync jobs that run in the background.
    Executes sync commands received from clients (WildlandSync instances).
    """

    @dataclass(frozen=True)
    class Request:
        """
        Sync command requested by a client.
        """
        client_id: int
        cmd: WlSyncCommand

    @dataclass(frozen=True)
    class EventFilter:
        """
        Filter data associated with event callback, needed to dispatch events.
        """
        client_id: int  # client that registered the callback
        container_id: Optional[str]  # None == match all
        types: Set[SyncApiEventType]

    @dataclass
    class SyncJob:
        """
        Data about a running sync job.
        Subclasses are free to include additional data if needed.
        """
        syncer: Optional[BaseSyncer] = None
        stop_event = threading.Event()

    def __init__(self):
        self.active = False
        self.client_id: int = 0
        self.handler_id: int = 0

        self.jobs: Dict[str, 'WlSyncManager.SyncJob'] = dict()  # container_id -> job
        self.jobs_lock = threading.Lock()

        # Queue of pending requests from clients. Subclass implementations should fill it
        # asynchronously after establishing connection with a client.
        self.requests: Queue[WlSyncManager.Request] = Queue()

        # client_id -> queue of pending responses to send
        # Subclass implementations should send these to appropriate client asynchronously.
        self.responses: Dict[int, Optional[Queue]] = dict()
        self.responses_lock = threading.Lock()

        # data needed to dispatch events: handler_id -> filter data
        self.event_filters: Dict[int, WlSyncManager.EventFilter] = dict()
        self.event_lock = threading.Lock()
        logger.debug('base init ok')

    def new_client_id(self) -> int:
        """
        Generate new unique client ID.
        """
        self.client_id += 1
        return self.client_id

    def new_handler_id(self) -> int:
        """
        Generate new unique event handler ID.
        """
        self.handler_id += 1
        return self.handler_id

    @wildland_result()
    def get_request(self) -> Tuple[WildlandResult, Optional[Request]]:
        """
        Get a sync command to be executed from internal command queue.
        :return: WildlandResult and Request if one is available, None if request queue is empty.
        """
        assert self.active
        try:
            return WildlandResult.OK(), self.requests.get_nowait()
        except Empty:
            return WildlandResult.OK(), None

    @wildland_result()
    def queue_response(self, client_id: int, resp_id: int, response: Any) -> WildlandResult:
        """
        Queue command reply or event to send to a client.
        :param client_id: client to send the response to
        :param resp_id: command ID if this is a command response, or handler ID if this is an event
        :param response: data to send (SyncEvent or tuple (WildlandResult, command data))
        :return: WildlandResult
        """
        with self.responses_lock:
            queue = self.responses[client_id]
            assert queue
            queue.put((resp_id, response))

        return WildlandResult.OK()

    @abc.abstractmethod
    def start(self) -> WildlandResult:
        """
        Start accepting commands from clients asynchronously.
        Commands should be inserted into self.requests.
        Replies and events should be sent to clients from self.responses asynchronously.
        """

    @wildland_result()
    def main(self) -> WildlandResult:
        """
        Main loop of the manager. Gets commands and executes them until interrupted by stop().
        """
        logger.info('main loop starting')
        while self.active:
            result, request = self.get_request()
            if not result.success:
                return result

            if request is None:
                time.sleep(POLL_TIMEOUT)
                continue

            logger.debug('processing %s', request)
            try:
                cmd_result, response = request.cmd.handle(self, request.client_id)
                if not cmd_result.success:
                    logger.warning('request %s failed: %s', request, cmd_result)

                result = self.queue_response(request.client_id, request.cmd.id,
                                             (cmd_result, response))
                if not result.success:
                    return result
            except Exception:
                logger.exception('WTF')

            # responses (and events) should be sent to clients asynchronously by subclass
            # implementations from self.responses

        logger.debug('main loop finished')
        return WildlandResult.OK()

    @abc.abstractmethod
    def stop(self) -> WildlandResult:
        """
        Stop accepting commands and stop all running jobs.
        """

    @staticmethod
    def event_match(event: SyncEvent, filters: 'WlSyncManager.EventFilter') -> bool:
        """
        Returns True if an event matches given fiter criteria.
        """
        if SyncApiEventType.from_raw(event) not in filters.types:
            return False

        if filters.container_id is None:  # match any job
            return True

        return filters.container_id == event.job_id

    def _event_handler(self, container_id: str, event: SyncEvent):
        """
        Process raw events coming from sync jobs. Filter according to registered callbacks
        and queue for dispatch to clients.
        """
        event.job_id = container_id

        for handler_id, filter_data in self.event_filters.items():
            if self.event_match(event, filter_data):
                with self.responses_lock:
                    queue = self.responses[filter_data.client_id]
                    assert queue
                    queue.put((handler_id, event))

    # TODO decorate handlers here in the base class instead of the subclasses
    # needs rework of the decorator to support that

    # TODO: allow returning just WildlandResult if no data sent back?
    # TODO these shouldn't be abstract, mostly

    @abc.abstractmethod
    def cmd_job_start(self, container_id: str, source_storage_id: str, target_storage_id: str,
                      continuous: bool, unidirectional: bool) \
            -> Tuple[WildlandResult, None]:
        """
        Handler for the JOB_START command. Starts a sync job in the background and returns
        immediately.
        """

    @abc.abstractmethod
    def cmd_job_stop(self, container_id: str, force: bool) -> Tuple[WildlandResult, None]:
        """
        Handler for the JOB_STOP command. Stops a sync job.
        If force is True, doesn't wait for the job to finish.
        """

    @WlSyncCommand.handler(WlSyncCommandType.JOB_PAUSE)
    def cmd_job_pause(self, container_id: str) -> Tuple[WildlandResult, None]:
        """
        Handler for the JOB_PAUSE command. Pauses a sync job.
        """
        logger.debug('pause handler: %s', container_id)
        return WildlandResult.error(WLErrorType.NOT_IMPLEMENTED,
                                    diagnostic_info=str(container_id)), None
        # raise NotImplementedError  # TODO need base syncer changes

    @WlSyncCommand.handler(WlSyncCommandType.JOB_RESUME)
    def cmd_job_resume(self, container_id: str) -> Tuple[WildlandResult, None]:
        """
        Handler for the JOB_RESUME command. Resumes a sync job.
        """
        return WildlandResult.error(WLErrorType.NOT_IMPLEMENTED), None
        # raise NotImplementedError  # TODO need base syncer changes

    # TODO handlers returned data should be Optional if failed

    @WlSyncCommand.handler(WlSyncCommandType.JOB_STATE)
    def cmd_job_state(self, container_id: str) -> Tuple[WildlandResult, SyncState]:
        """
        Handler for the JOB_STATE command. Returns job's overall state.
        """
        if not self.active:
            return WildlandResult.error(WLErrorType.SYNC_MANAGER_NOT_ACTIVE,
                                        diagnostic_info=container_id), SyncState.STOPPED

        with self.jobs_lock:
            try:
                job = self.jobs[container_id]
                assert job.syncer
                return WildlandResult.OK(), job.syncer.state
            except KeyError:
                return WildlandResult.error(WLErrorType.SYNC_FOR_CONTAINER_NOT_RUNNING,
                                            diagnostic_info=container_id), SyncState.STOPPED

    @WlSyncCommand.handler(WlSyncCommandType.JOB_DETAILS)
    def cmd_job_details(self, container_id: str) -> Tuple[WildlandResult, Tuple[SyncApiFileState]]:
        """
        Handler for the JOB_DETAILS command. Returns state of all files in the job.
        """
        return WildlandResult.error(WLErrorType.NOT_IMPLEMENTED), ()
        # raise NotImplementedError  # TODO need base syncer changes

    @WlSyncCommand.handler(WlSyncCommandType.JOB_FILE_DETAILS)
    def cmd_job_file_details(self, container_id: str, path: str) \
            -> Tuple[WildlandResult, SyncApiFileState]:
        """
        Handler for the JOB_FILE_DETAILS command. Returns state of a particular file in the job.
        """
        return WildlandResult.error(WLErrorType.NOT_IMPLEMENTED), ()
        # raise NotImplementedError  # TODO need base syncer changes

    @WlSyncCommand.handler(WlSyncCommandType.JOB_SET_CALLBACK, client_id=True)
    def cmd_job_set_callback(self, client_id: int, container_id: Optional[str],
                             filters: Set[SyncApiEventType]) \
            -> Tuple[WildlandResult, Optional[int]]:
        """
        Handler for the JOB_SET_CALLBACK command. Returns callback ID if successful.
        Manager should start sending specified events to the calling client.
        """
        with self.event_lock:
            handler_id = self.new_handler_id()
            if len(filters) == 0:
                filters = set(SyncApiEventType)

            self.event_filters[handler_id] = WlSyncManager.EventFilter(client_id, container_id,
                                                                       filters)

        return WildlandResult.OK(), handler_id

    @WlSyncCommand.handler(WlSyncCommandType.JOB_CLEAR_CALLBACK)
    def cmd_job_clear_callback(self, callback_id: int) -> Tuple[WildlandResult, None]:
        """
        Handler for the JOB_CLEAR_CALLBACK command. Manager should stop sending events matching
        passed callback ID.
        """
        with self.event_lock:
            if callback_id not in self.event_filters.keys():
                return WildlandResult.error(WLErrorType.SYNC_CALLBACK_NOT_FOUND,
                                            diagnostic_info=str(callback_id)), None
            self.event_filters.pop(callback_id)

        return WildlandResult.OK(), None

    @WlSyncCommand.handler(WlSyncCommandType.FORCE_FILE)
    def cmd_force_file(self, container_id: str, path: str, source_storage_id: str,
                       target_storage_id: str) -> Tuple[WildlandResult, None]:
        """
        Handler for the FORCE_FILE command. Force sync one file between storages.
        """
        return WildlandResult.error(WLErrorType.NOT_IMPLEMENTED), None
        # raise NotImplementedError  # TODO

    @WlSyncCommand.handler(WlSyncCommandType.SHUTDOWN)
    def cmd_shutdown(self) -> Tuple[WildlandResult, None]:
        """
        Handler for the SHUTDOWN command. Stops the manager and all sync jobs.
        """
        return self.stop(), None

    def _job_worker(self, job_id: str, source_storage_id: str, target_storage_id: str,
                    continuous: bool, unidirectional: bool,
                    event_handler: Callable[[SyncEvent], None],
                    stop_event: threading.Event) -> WildlandResult:
        """
        Internal method that hosts a sync job. Normally runs in a background thread.
        Returns only after the job is finished/stopped.
        :param job_id: ID of the sync job (normally container ID)
        :param source_storage_id: storage_id, in the format as in Wildland Core API, of the source
                                  storage (order of source/target is relevant only for
                                  unidirectional sync, which transfers data from source to target)
        :param target_storage_id: storage_id, in the format as in Wildland Core API, of the target
                                  storage (order of source/target is relevant only for
                                  unidirectional sync, which transfers data from source to target)
        :param continuous: should sync be continuous or one-shot
        :param unidirectional: should sync go both ways or one-way only
        :param event_handler: callback that receives all sync events from this job
        :param stop_event: event that stops the job asynchronously
        :return: WildlandResult showing if it was successful.
        """
        result = WildlandResult()
        logger.debug('worker start')
        syncer = None

        try:
            source_params = _params_from_wl_storage_id(source_storage_id)  # TODO
            target_params = _params_from_wl_storage_id(target_storage_id)
            source_backend = StorageBackend.from_params(source_params)
            target_backend = StorageBackend.from_params(target_params)

            syncer = BaseSyncer.from_storages(source_storage=source_backend,
                                              target_storage=target_backend,
                                              log_prefix=job_id,
                                              one_shot=not continuous,
                                              continuous=continuous,
                                              unidirectional=unidirectional,
                                              can_require_mount=False)

            # we collect all events, filtering/dispatching is done on the higher level
            # syncer only supports one callback
            syncer.set_event_callback(event_handler)

            with self.jobs_lock:
                assert job_id in self.jobs.keys(), f'job {job_id} not initialized correctly'
                self.jobs[job_id].syncer = syncer

            if continuous:
                syncer.start_sync()
                logger.debug('worker wait')
                stop_event.wait()
                #if self.test_error:
                #    raise WildlandError('Test sync exception')
            else:
                # TODO way to abort one shot sync
                syncer.one_shot_sync(unidirectional)
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
            logger.exception('Sync worker exception:')
            if syncer:
                syncer.notify_event(SyncErrorEvent(str(ex)))
                syncer.notify_event(SyncStateEvent(SyncState.ERROR))
                # syncer didn't catch the exception so it didn't update its state
                syncer.state = SyncState.ERROR
        finally:
            if continuous and syncer:
                syncer.stop_sync()

        logger.debug('worker end')
        return result
