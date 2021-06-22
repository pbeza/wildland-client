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
Wildland Rest API configuration
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from wildland.api.routers import bridge, container, file, instance, storage, user

app = FastAPI(
    title="Wildland API",
    description="The Rest API made for Wildland Graphical User Interface",
    version="0.0.1-alpha.0",
)  # dependencies=[Depends(get_query_token)]

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bridge.router)
app.include_router(container.router)
app.include_router(file.router)
app.include_router(instance.router)
app.include_router(storage.router)
app.include_router(user.router)


@app.get("/")
async def root():
    """Root api url provides given welcome message, including `docs` information."""
    return {
        "message": "Welcome to Wildland API! To get more information about endpoints, have a glance over '/docs' path." # pylint: disable=line-too-long
    }
