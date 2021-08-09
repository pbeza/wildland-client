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
Wildland Event Websocket
"""

import asyncio
import logging
import os
import select
from fastapi import APIRouter
from fastapi.websockets import WebSocket, WebSocketDisconnect

from wildland.api.utils import (
    ProcessExecManager,
    ConnectionManager,
)
from wildland.ipc import EventIPC, IPC_NAME


logger = logging.getLogger("gunicorn.error")
router = APIRouter()
conn_manager = ConnectionManager()
exec_manager = ProcessExecManager()

try:
    os.mkfifo(IPC_NAME)
except FileExistsError:
    pass
# Pipe in non-blocking mode for reading
fifo = os.open(IPC_NAME, os.O_RDONLY | os.O_NONBLOCK)


def get_message(ipc: int) -> str:
    """Get a message from the named pipe."""
    msg_size_bytes = os.read(ipc, 4)
    msg_size = EventIPC.decode_msg_size(msg_size_bytes)
    msg_content = os.read(ipc, msg_size).decode("utf8")
    return msg_content


async def status_event_generator(websocket: WebSocket, manager: ConnectionManager):
    """Watch IPC communication to yield emitted event data for Websocket"""
    await manager.connect(websocket)
    try:
        try:
            # Create a polling object to monitor the pipe for new event data
            poll = select.poll()
            poll.register(fifo, select.POLLIN)
            try:
                while True:
                    # Check if data to read, timeout after a second
                    if (fifo, select.POLLIN) in poll.poll(1000):
                        msg = get_message(fifo)
                        yield msg
                    else:
                        # If no data, sleep a second
                        await asyncio.sleep(1)
            finally:
                poll.unregister(fifo)
        finally:
            os.close(fifo)

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/stream")
async def runStatus(websocket: WebSocket):
    """Event stream websocket endpoint"""
    executor = exec_manager.get_executor()
    event_generator = await ProcessExecManager.run_in_process(
        executor, status_event_generator, websocket, conn_manager
    )
    async for message in event_generator:
        await conn_manager.broadcast(message)


@router.on_event("startup")
async def startup_event():
    """Create ProcessPoolExecutor"""
    exec_manager.create_executor()


@router.on_event("shutdown")
async def on_shutdown():
    """Shutdown ProcessPoolExecutor"""
    exec_manager.shutdown()
