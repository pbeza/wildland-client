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
Internal API for Wildland sync operations (sync commands).
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Any, get_type_hints, Tuple, Optional, Set, Union, List

from wildland.core.wildland_result import WildlandResult
from wildland.core.wildland_sync_api import SyncApiEventType
from wildland.storage_sync.base import SyncState, SyncFileInfo

POLL_TIMEOUT = 0.00001  # timeout (seconds) for connection polling


class WlSyncCommandType(Enum):
    """
    Type of sync command. Includes type annotation for its handler.
    The annotation should be in the format of {'param_name': type, 'name': type, ...}
    Param name 'return' signifies return type.
    Handlers are expected to return WildlandResult to indicate success. If more data needs
    to be returned, it should be contained in a tuple with WildlandResult.
    """
    # note: auto() values are not picklable
    JOB_START = 1, {'container_id': str, 'source_params': dict, 'target_params': dict,
                    'continuous': bool, 'unidirectional': bool, 'return': WildlandResult}
    JOB_STOP = 2, {'container_id': str, 'force': bool, 'return': WildlandResult}
    JOB_PAUSE = 3, {'container_id': str, 'return': WildlandResult}
    JOB_RESUME = 4, {'container_id': str, 'return': WildlandResult}
    JOB_STATE = 5, {'container_id': str, 'return': Tuple[WildlandResult, Optional[SyncState]]}
    JOB_DETAILS = 6, {'container_id': str,
                      'return': Tuple[WildlandResult, List[SyncFileInfo]]}
    JOB_FILE_DETAILS = 7, {'container_id': str, 'path': str,
                           'return': Tuple[WildlandResult, Optional[SyncFileInfo]]}
    JOB_SET_CALLBACK = 8, {'container_id': Optional[str], 'filters': Set[SyncApiEventType],
                           'return': Tuple[WildlandResult, Optional[int]]}
    JOB_CLEAR_CALLBACK = 9, {'callback_id': int, 'return': WildlandResult}
    FORCE_FILE = 10, {'container_id': str, 'path': str, 'source_storage_id': str,
                      'target_storage_id': str, 'return': WildlandResult}
    SHUTDOWN = 11, {'return': WildlandResult}

    # handler for particular command type
    handler: Callable[..., Union[WildlandResult, Tuple[WildlandResult, Any]]]
    client_id: bool

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return str(self.name)


@dataclass(frozen=True)
class WlSyncCommand:
    """
    Internal command for the sync manager. Constructed by clients and sent to the manager.
    """
    id: int  # should be unique per client
    type: WlSyncCommandType
    params: dict

    @staticmethod
    def from_args(cmd_id: int, cmd: WlSyncCommandType, **kwargs) -> 'WlSyncCommand':
        """
        Create a command instance from keyword arguments.
        """
        # TODO: validate once, not on every instantiation. pylint plugin?
        for name, sig in cmd.value[1].items():
            if name == 'return':
                continue

            assert name in kwargs, f'Missing argument {name} for command {cmd}'

            # TODO Subscripted generics cannot be used with class and instance checks
            # assert isinstance(kwargs[name], sig), \
            #     f'Invalid argument {name} type for command {cmd}'

        return WlSyncCommand(cmd_id, cmd, kwargs)

    @staticmethod
    def handler(cmd: WlSyncCommandType, client_id: bool = False):
        """
        Decorator for command handlers. Required one handler per WlSyncCommandType.
        Handler's signature must match one expected in the WlSyncCommandType definition.
        :param cmd: command type this handler applies to
        :param client_id: if True, handler should accept a client_id:int parameter that will be
                          supplied by the manager.
        """
        def _wrapper(func: Callable):
            assert not hasattr(cmd, 'handler'), f'Duplicate handlers for {cmd}'
            sig = get_type_hints(func)

            if client_id:
                assert 'client_id' in sig.keys(), f'Invalid handler for {cmd} {cmd.client_id}'
                assert sig['client_id'] == int, f'Invalid handler for {cmd}'
                sig.pop('client_id')

            assert sig == cmd.value[1], f'Invalid handler for {cmd}'

            # see https://github.com/python/mypy/issues/708
            cmd.handler = func  # type: ignore
            cmd.client_id = client_id

            return func

        return _wrapper

    @staticmethod
    def check_handlers():
        """
        Check that all command types have valid handlers.
        """
        for cmd in WlSyncCommandType:
            assert hasattr(cmd, 'handler'), f'Handler not found for {cmd}'

    def handle(self, instance: object, client_id: int = 0) -> Tuple[WildlandResult, Any]:
        """
        Call the handler assigned for this command type.
        :param instance: WlSyncManager instance that contains handler methods.
        :param client_id: client ID of the requestor.
        :return: WildlandResult and data returned by the handler, data can be None.
        """

        if self.type.client_id:
            self.params['client_id'] = client_id

        ret = self.type.handler(instance, **self.params)

        if isinstance(ret, WildlandResult):
            return ret, None

        assert isinstance(ret, tuple)
        return ret
