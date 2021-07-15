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
Wildland Forest Rest API
"""

from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx, ensure_wl_mount
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()


@router.get("/forest/", tags=["forest"], dependencies=[Depends(ensure_wl_mount)])
async def read_forests(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland forests as a list"""
    storages = list(ctx.fs_client.get_info().values())
    bridges = ctx.client.load_all(WildlandObject.Type.BRIDGE)
    forest_list = []
    for storage in storages:
        for path in storage['paths']:
            for bridge in bridges:
                if path == bridge.local_path:
                    forest_list.append(bridge.local_path)

    return list(set(forest_list))

@router.get("/forest/{name}", tags=["forest"])
async def read_forest(name: str):
    """Returns information of specific wildland forest"""
    return {"name": name}
