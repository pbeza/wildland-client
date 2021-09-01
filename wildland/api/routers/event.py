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
from asyncio.streams import StreamReader, StreamWriter
from typing import AsyncGenerator
from fastapi import APIRouter
from fastapi.websockets import WebSocket

from wildland.api.utils import (
    ConnectionManager
)
from wildland.ipc import EventIPC, IPC_NAME


class StatusEventsManager(ConnectionManager):
    """Websocket Connection Manager sending status events"""

    server = None

    @staticmethod
    async def get_messages(reader: asyncio.StreamReader) -> AsyncGenerator[str, None]:
        """Get messages from the unix socket."""
        while True:
            msg_size_bytes = None
            try:
                msg_size_bytes = await reader.readexactly(4)
            except asyncio.IncompleteReadError:
                return
            msg_size = EventIPC.decode_msg_size(msg_size_bytes)
            msg_content = (await reader.readexactly(msg_size)).decode("utf8")
            yield msg_content

    async def _handle_writer(self, reader: StreamReader, _writer: StreamWriter):
        """Broadcast recieved messages to the websocket connections"""
        async for message in self.get_messages(reader):
            await self.broadcast(message)

    async def generate_messages(self):
        """Setup Unix Socket Server, Recieve status messages from a unix
           socket clients and broadcast them to all websocket connections
        """
        loop = asyncio.get_event_loop()
        self.server = await asyncio.start_unix_server(
            self._handle_writer, path=IPC_NAME, loop=loop
        )

    async def shutdown(self):
        if self.server:
            self.server.close()
        return await super().shutdown()


router = APIRouter()
conn_manager = StatusEventsManager()


@router.websocket("/stream")
async def runStatus(websocket: WebSocket):
    """Event stream websocket endpoint"""
    await conn_manager.handle(websocket)


@router.on_event("shutdown")
async def shutdown_event():
    """Shutdown StatusEventsManager"""
    await conn_manager.shutdown()
