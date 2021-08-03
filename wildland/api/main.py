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
from starlette.requests import Request
from wildland.api.routers import bridge, container, event, file, forest, storage, user


API_VERSION = "0.0.1"
app = FastAPI(openapi_url=None)  # dependencies=[Depends(get_query_token)]
api = FastAPI(openapi_url=None)
api_with_version = FastAPI(
    title="Wildland API",
    description="The Rest API made for Wildland Graphical User Interface",
    version=f"{API_VERSION}-alpha.0",
)

origins = ["*"]


api_with_version.include_router(bridge.router)
api_with_version.include_router(container.router)
api_with_version.include_router(event.router)
api_with_version.include_router(file.router)
api_with_version.include_router(forest.router)
api_with_version.include_router(storage.router)
api_with_version.include_router(user.router)


@api_with_version.get("/")
async def root(request: Request):
    """Root api url provides given welcome message, including `docs` information."""
    return {
        "message": f"Welcome to Wildland API! \
To get more information about endpoints, have a glance over \
'{request.scope.get('root_path')}/docs' path."
    }


api.mount(f"/{API_VERSION}", api_with_version)
app.mount("/api", api)
