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
Wildland Storage Rest API
"""

from fastapi import APIRouter, Depends, HTTPException
from wildland.api.dependency import ContextObj, get_ctx
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()


@router.get("/storage/", tags=["storage"])
async def read_storages(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland storages as a list"""
    storages = ctx.client.load_all(WildlandObject.Type.STORAGE)

    backend_list = []
    for container in ctx.client.load_all(WildlandObject.Type.CONTAINER):
        for backend in container.manifest._fields.get("backends", {}).get(
            "storage", []
        ):
            if not backend:
                continue

            if not isinstance(backend, str):
                backend_list.append(backend)

    return list(storages) + backend_list


@router.get("/storage/{name}", tags=["storage"])
async def read_storage(name: str):
    """Returns information of specific wildland storage"""
    raise HTTPException(status_code=404, detail="Not Implemented")
