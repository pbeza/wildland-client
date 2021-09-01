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
import struct

import asyncio


IPC_NAME = PurePosixPath("/tmp/wildland_event_ipc")


class EventIPC:
    """Creates Unidirectional IPC for Event-Data Streaming"""

    def __init__(self, is_enabled):
        self.is_enabled = is_enabled
        if not is_enabled:
            return
        self.reader, self.writer = self.handle_unix_connection()

    @staticmethod
    def handle_unix_connection():
        """Sets up unix server for an ipc connection"""
        loop = asyncio.get_event_loop()
        try:
            conn_fut = asyncio.open_unix_connection(IPC_NAME, loop=loop)
            return loop.run_until_complete(conn_fut)
        except FileNotFoundError:
            return None, None

    def emit(self, topic, label):
        """Emits given topic and label as bytes"""
        if not self.is_enabled:
            return
        if not self.writer:
            return

        data = json.dumps(dict(topic=topic, label=label))
        content = f"{data}".encode("utf8")
        message = EventIPC.create_msg(content)
        self.writer.write(message)

    def close(self):
        """Closes named StreamWriter"""
        self.writer.close()

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
        """Creates PIPE message body"""
        size = len(content)
        return EventIPC.encode_msg_size(size) + content
