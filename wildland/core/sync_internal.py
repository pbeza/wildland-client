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
Internal API for Wildland sync operations (sync commands).
"""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Dict, Any, get_type_hints, get_origin, get_args, Tuple

from wildland.core.wildland_result import WildlandResult

POLL_TIMEOUT = 0.00001  # timeout (seconds) for connection polling


class WlSyncCommandType(Enum):
    """
    Type of sync command.
    """
    # TODO: set expected handler signature here?
    JOB_START = auto()  # cid, s1: params, s2: params, cont: bool, uni: bool
    JOB_STOP = auto()  # cid
    JOB_PAUSE = auto()  # cid
    JOB_RESUME = auto()  # cid
    JOB_STATE = auto()  # cid -> SyncState
    JOB_DETAILS = auto()  # cid -> tuple(file state)
    JOB_FILE_DETAILS = auto()  # cid, path: str -> file state
    JOB_SET_CALLBACK = auto()  # cid, filters -> handler id
    JOB_CLEAR_CALLBACK = auto()  # handler id
    FORCE_FILE = auto()  # cid, path, s1, s2 / synchronous?
    SHUTDOWN = auto()  # - / stop processing

    handler: Callable  # handler for particular command type
    sig: Dict[str, Any]  # signature of the handler (params/types)
    client_id: bool  # whether the handler requires client_id param


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
        # TODO: validate once, not on every instantiation. possible?
        for arg in cmd.sig.keys():
            assert arg in kwargs, f'Missing argument {arg} for command {cmd}'
            assert isinstance(kwargs[arg], cmd.sig[arg]), \
                f'Invalid argument {arg} type for command {cmd}'
        return WlSyncCommand(cmd_id, cmd, kwargs)

    @staticmethod
    def handler(cmd: WlSyncCommandType, client_id: bool = False):
        """
        Decorator for command handlers. Required one handler per WlSyncCommandType.
        Handlers can have different parameter list depending on command type.
        :param cmd: command type this handler applies to
        :param client_id: if true, the handler is expected take a client_id parameter (before other
                          keyword parameters)
        :return: A tuple (WildlandResult, Any). First element indicates success,
                 second is the data returned (can be None).
        """
        def _wrapper(func: Callable):
            assert not hasattr(cmd, 'handler'), f'Duplicate handlers for {cmd}'
            sig = get_type_hints(func)
            assert 'return' in sig, f'Return type not specified in handler for {cmd}'
            ret = sig['return']
            assert_msg = f'Invalid return type of handler for {cmd}'
            assert get_origin(ret) == tuple, assert_msg
            args = get_args(ret)
            assert len(args) == 2, assert_msg
            assert args[0] == WildlandResult, assert_msg

            # see https://github.com/python/mypy/issues/708
            cmd.handler = func  # type: ignore

            sig.pop('return')  # not needed any more

            if client_id:
                assert 'client_id' in sig, f'client_id param missing in handler for {cmd}'
                cmd.client_id = True
                sig.pop('client_id')  # this param is only for server side
            else:
                cmd.client_id = False

            cmd.sig = sig
            return func

        return _wrapper

    @staticmethod
    def check_handlers():
        """
        Check that all command types have valid handlers.
        """
        for cmd in WlSyncCommandType:
            assert hasattr(cmd, 'handler'), f'Handler not found for {cmd}'
            assert hasattr(cmd, 'sig'), f'Handler signature not found for {cmd}'
            assert isinstance(cmd.sig, Dict)

    def handle(self, instance: object, client_id: int) -> Tuple[WildlandResult, Any]:
        """
        Call the handler assigned for this command type.
        :param instance: WlSyncManager instance that contains handler methods.
        :param client_id: ID of the client that requested this command.
        :return: WildlandResult and data returned by the handler, data can be None.
        """
        if self.type.client_id:
            return self.type.handler(instance, client_id, **self.params)

        return self.type.handler(instance, **self.params)
