# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Muhammed Tanrikulu <muhammed@wildland.io>,
#                    Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
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
Wildland Event Websocket
"""

import asyncio
import os
from typing import AsyncGenerator
from fastapi import APIRouter
from fastapi.websockets import WebSocket

from wildland.api.utils import (
    ConnectionManager
)
from wildland.ipc import EventIPC, IPC_NAME


class StatusEventsManager(ConnectionManager):
    """Websocket Connection Manager sending status events"""

    @staticmethod
    def create_fifo():
        """Create a fifo pipe for communication with wl process"""
        try:
            os.mkfifo(IPC_NAME)
        except FileExistsError:
            pass

    @staticmethod
    async def get_messages(reader: asyncio.StreamReader) -> AsyncGenerator[str, None]:
        """Get messages from the named pipe."""
        while True:
            msg_size_bytes = None
            try:
                msg_size_bytes = await reader.readexactly(4)
            except asyncio.IncompleteReadError:
                return
            msg_size = EventIPC.decode_msg_size(msg_size_bytes)
            msg_content = (await reader.readexactly(msg_size)).decode("utf8")
            yield msg_content

    async def handle_single_pipe_connection(self):
        """Open a pipe and read all the messages.

           Due to the nature of a fifo pipe, it needs to be closed and
           opened again to wait for another writer (otherwise it will
           continuously return EOF, until a another writer connects).
        """
        # Pipe in non-blocking mode for reading
        # pylint: disable=consider-using-with
        fifo = open(os.open(IPC_NAME, os.O_RDONLY | os.O_NONBLOCK), 'rb')
        reader = asyncio.StreamReader()
        # this protocol and transport is only used as a way to connect the
        # reader to the actual pipe
        loop = asyncio.get_event_loop()
        read_protocol = asyncio.StreamReaderProtocol(reader)
        read_transport, _ = await loop.connect_read_pipe(
            lambda: read_protocol, fifo)
        try:
            async for message in self.get_messages(reader):
                await self.broadcast(message)
        finally:
            read_transport.close()

    async def generate_messages(self):
        """Read status messages from a fifo and broadcast them to all websocket
           connections"""
        self.create_fifo()
        while True:
            await self.handle_single_pipe_connection()


router = APIRouter()
conn_manager = StatusEventsManager()
conn_manager.create_fifo()


@router.websocket("/stream")
async def runStatus(websocket: WebSocket):
    """Event stream websocket endpoint"""
    await conn_manager.handle(websocket)


@router.on_event("shutdown")
async def shutdown_event():
    """Shutdown StatusEventsManager"""
    await conn_manager.shutdown()
