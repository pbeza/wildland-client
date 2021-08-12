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
Wildland Bridge Rest API
"""

from fastapi import APIRouter, Depends, HTTPException
from wildland.api.dependency import ContextObj, get_ctx
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()


@router.get("/bridge/", tags=["bridge"])
async def read_bridges(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland bridges as a list"""
    bridges = ctx.client.load_all(WildlandObject.Type.BRIDGE)
    bridge_list = []
    for bridge in bridges:
        bridge_obj = bridge.to_manifest_fields(inline=False)
        bridge_list.append(bridge_obj)

    return bridge_list


@router.get("/bridge/{name}", tags=["bridge"])
async def read_bridge(name: str):
    """Returns information on specific wildland bridge"""
    raise HTTPException(status_code=404, detail="Not Implemented")
