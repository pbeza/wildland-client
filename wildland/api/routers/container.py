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

from fastapi import APIRouter, Depends, HTTPException
from wildland.api.dependency import ContextObj, get_ctx, ensure_wl_mount
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()


@router.get("/container/", tags=["container"], dependencies=[Depends(ensure_wl_mount)])
async def read_containers(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland containers as a list"""
    storages = list(ctx.fs_client.get_info().values())
    containers = ctx.client.load_all(WildlandObject.Type.CONTAINER)
    container_list = []
    for container in containers:
        container_obj = container.to_manifest_fields(inline=False)
        container_obj['mounted'] = False
        container_list.append(container_obj)

        for storage in storages:
            paths = storage["paths"]
            (smaller, bigger) = sorted([paths, container.paths], key=len)
            bigger_set = set(bigger)
            if any(item in bigger_set for item in smaller):
                container_obj['mounted'] = True
    return container_list


@router.get("/container/{name}", tags=["container"])
async def read_container(name: str):
    """Returns information of specific wildland container"""
    raise HTTPException(status_code=404, detail="Not Implemented")
