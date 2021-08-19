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
import concurrent.futures
import errno
import logging
import os
from typing import Optional
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


def get_message(ipc: int) -> Optional[str]:
    """Get a message from the named pipe."""
    msg_size_bytes = None
    try:
        msg_size_bytes = os.read(ipc, 4)
    except IOError as e:
        if e.errno == errno.EWOULDBLOCK:
            pass
    if not msg_size_bytes:
        return None
    msg_size = EventIPC.decode_msg_size(msg_size_bytes)
    msg_content = os.read(ipc, msg_size).decode("utf8")
    return msg_content


async def watch_pipe(loop, fd) -> None :
    """Add named pipe into asyncio reader and resolve future in any change"""
    future: asyncio.Future = asyncio.Future()
    loop.add_reader(fd, future.set_result, None)
    future.add_done_callback(lambda f: loop.remove_reader(fd))
    await future


async def status_event_generator(websocket: WebSocket, manager: ConnectionManager):
    """Watch IPC communication to yield emitted event data for Websocket"""
    await manager.connect(websocket)
    loop = asyncio.get_event_loop()
    try:
        while True:
            await watch_pipe(loop, fifo)
            with concurrent.futures.ThreadPoolExecutor() as pool:
                msg = await loop.run_in_executor(pool, get_message, fifo)
                if msg:
                    yield msg
                else:
                    asyncio.sleep(1)
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
