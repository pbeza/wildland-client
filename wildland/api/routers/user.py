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
Wildland User Rest API
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from wildland.api.dependency import ContextObj, get_ctx, ensure_wl_mount
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()
logger = logging.getLogger("gunicorn.error")


@router.get("/user/", tags=["user"], dependencies=[Depends(ensure_wl_mount)])
async def read_users(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland users as a list"""
    storages = list(ctx.fs_client.get_info().values())
    users = list(ctx.client.load_all(WildlandObject.Type.USER))
    for user in users:
        setattr(user, "mounted", False)
        for storage in storages:
            main_path = storage["paths"][0]
            if user.owner in str(main_path):
                setattr(user, "mounted", True)
    return users


@router.get("/user/me", tags=["user"])
async def read_user_me():
    """Returns information of default wildland user for current instance"""
    raise HTTPException(status_code=404, detail="Not Implemented")


@router.get("/user/{username}", tags=["user"])
async def read_user(username: str):
    """Returns information of specific wildland user"""
    raise HTTPException(status_code=404, detail="Not Implemented")
