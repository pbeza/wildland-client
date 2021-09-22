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

"""
Wildland Interprocess Communication Channel based on NamedPipe
"""
import json
from pathlib import PurePosixPath
import socket
import struct


IPC_NAME = PurePosixPath("/tmp/wildland_event_ipc")


class EventIPC:
    """Establishes Unidirectional IPC connection for Event-Data Streaming"""

    def __init__(self, is_enabled):
        self.is_enabled = is_enabled
        if not is_enabled:
            return
        self.client = self.handle_unix_connection()

    def handle_unix_connection(self):
        """Connects to the unix server for an ipc connection"""
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(IPC_NAME))
            return client
        except FileNotFoundError:
            return None

    def emit(self, topic, label):
        """Emits given topic and label as bytes"""
        if not self.is_enabled:
            return
        if not self.client:
            return

        data = json.dumps(dict(topic=topic, label=label))
        content = f"{data}".encode("utf8")
        message = EventIPC.create_msg(content)
        self.client.send(message)

    def close(self):
        """Closes unix socket connection"""
        self.client.close()

    @staticmethod
    def encode_msg_size(size: int) -> bytes:
        """Encodes data/message size"""
        return struct.pack("<I", size)

    @staticmethod
    def decode_msg_size(size_bytes: bytes) -> int:
        """Decodes data/message size"""
        return struct.unpack("<I", size_bytes)[0]

    @staticmethod
    def create_msg(content: bytes) -> bytes:
        """Creates message body"""
        size = len(content)
        return EventIPC.encode_msg_size(size) + content
