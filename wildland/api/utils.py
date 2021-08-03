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
Wildland Rest API Utilities
"""
from concurrent.futures.process import ProcessPoolExecutor
import asyncio
from typing import List

from fastapi.websockets import WebSocket


class ConnectionManager:
    """Unidirectional Websocket Connection Manager"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept websocket connections"""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Close websocket connections"""
        self.active_connections.remove(websocket)

    async def broadcast(self, message: object):
        """Broadcast Messages to the connected peers"""
        for connection in self.active_connections:
            await connection.send_json(message)


class ProcessExecManager:
    """Manager Abstraction for Process Pool Executor"""

    def __init__(self):
        self.executor = None

    async def create_executor(self):
        """Creates Process Pool Executor"""
        self.executor = ProcessPoolExecutor()

    def get_executor(self):
        """Return Process Pool Executor, if doesn't exist create one"""
        if not self.executor:
            self.create_executor()
        return self.executor

    async def shutdown(self):
        """Shutdown Process Pool Executor"""
        if not self.executor:
            raise ValueError(
                "Please create an executor first by 'create_executor' method"
            )
        await self.executor.shutdown()

    @staticmethod # Due to unpicklable method issue, had to convert into static method
    async def run_in_process(executor, fn, *args):
        """Executes given function in subprocess worker"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            executor, fn, *args
        )
