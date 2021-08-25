# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Muhammed Tanrikulu <muhammed@wildland.io>
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
Wildland Rest API Utilities
"""
import abc
from concurrent.futures.process import ProcessPoolExecutor
from typing import List, Optional, Tuple

import asyncio
from fastapi.websockets import WebSocket
from starlette.websockets import WebSocketDisconnect


class ConnectionManager:
    """Unidirectional Websocket Connection Manager"""

    def __init__(self):
        # keep a future to notify when connection is terminated
        self.active_connections: List[Tuple[WebSocket, asyncio.Future]] = []
        # a task generating and broadcasting messages
        self.task: Optional[asyncio.Task] = None

    async def handle(self, websocket: WebSocket):
        """Accept websocket connections and send messages to it"""
        await websocket.accept()
        disconnect_future: asyncio.Future = asyncio.Future()
        self.active_connections.append((websocket, disconnect_future))
        if self.task is None:
            # have just one task generating messages, create it on first connection
            self.task = asyncio.create_task(self.generate_messages())
        # wait for send error / connection close or disconnect_all
        await disconnect_future

        self.active_connections.remove((websocket, disconnect_future))

    async def broadcast(self, message: object):
        """Broadcast Messages to the connected peers"""
        for connection, disconnect in self.active_connections:
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                disconnect.set_result(None)

    def disconnect_all(self):
        """Disconnect all clients"""
        for _, disconnect in self.active_connections:
            disconnect.set_result(None)

    @abc.abstractmethod
    async def generate_messages(self):
        """A function that generates messages. It should use `self.broadcast`
           to send them.
           A subclass must override this method.
        """

    async def shutdown(self):
        """Shutdown connection manager, stop generating messages"""
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.disconnect_all()


class ProcessExecManager:
    """Manager Abstraction for Process Pool Executor"""

    def __init__(self):
        self.executor = None

    def create_executor(self):
        """Creates Process Pool Executor"""
        # pylint: disable=consider-using-with
        self.executor = ProcessPoolExecutor()

    def get_executor(self):
        """Return Process Pool Executor, if doesn't exist create one"""
        if not self.executor:
            self.create_executor()
        return self.executor

    def shutdown(self):
        """Shutdown Process Pool Executor"""
        if not self.executor:
            raise ValueError(
                "Please create an executor first by 'create_executor' method"
            )
        self.executor.shutdown()
        self.executor = None

    @staticmethod # Due to unpicklable method issue, had to convert into static method
    async def run_in_process(executor, fn, *args):
        """Executes given function in subprocess worker"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            executor, fn, *args
        )
