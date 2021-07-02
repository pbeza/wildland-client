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
Wildland Container Rest API
"""

import logging
from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from wildland.api.dependency import ContextObj, get_ctx
from wildland.exc import WildlandError
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()
logger = logging.getLogger("gunicorn.error")


@router.get("/container/", tags=["container"])
async def read_containers(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland containers as a list"""

    try:
        ctx.fs_client.ensure_mounted()
    except WildlandError:
        return Response(
            content="Wildland is not mounted",
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        )

    storages = list(ctx.fs_client.get_info().values())
    containers = ctx.client.load_all(WildlandObject.Type.CONTAINER)
    container_list = []
    for container in containers:
        setattr(container, "mounted", False)
        container_obj = container.__dict__
        del container_obj["client"]
        container_list.append(container_obj)

        for storage in storages:
            paths = storage["paths"]
            (smaller, bigger) = sorted([paths, container.paths], key=len)
            bigger_set = set(bigger)
            if any(item in bigger_set for item in smaller):
                setattr(container, "mounted", True)
    return container_list


@router.get("/container/{name}", tags=["container"])
async def read_container(name: str):
    """Returns information of specific wildland container"""
    return {"name": name}
