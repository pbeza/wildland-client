# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Muhammed Tanrikulu <muhammed@wildland.io>
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

# pylint: disable=missing-docstring,redefined-builtin, not-context-manager

from unittest.mock import patch
from wildland.ipc import EventIPC


class MockSocket:
    """Mock for Unix Socket Client"""
    def __init__(self, _family, _type):
        pass

    @staticmethod
    def connect(_path: str):
        pass

    @staticmethod
    def send(_message):
        pass

    @staticmethod
    def close():
        pass


def test_event_ipc_disabled():
    ipc = EventIPC(is_enabled=False)
    ipc.emit(topic="WL_TEST", label="EMIT")
    ipc.close()


def test_event_ipc_no_connection():
    ipc = EventIPC(is_enabled=True)
    ipc.emit(topic="WL_TEST", label="EMIT")
    ipc.close()


@patch("socket.socket", MockSocket)
def test_event_ipc():
    ipc = EventIPC(is_enabled=True)
    ipc.emit(topic="WL_TEST", label="EMIT")
    ipc.close()


def test_encode_decode_msg():
    message_size = 100
    msg_bytes = EventIPC.encode_msg_size(message_size)
    decoded_message_size = EventIPC.decode_msg_size(msg_bytes)
    assert message_size == decoded_message_size
