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

from fastapi import APIRouter, Depends, HTTPException
from wildland.api.dependency import ContextObj, get_ctx, ensure_wl_mount


router = APIRouter()


@router.get("/forest/", tags=["forest"], dependencies=[Depends(ensure_wl_mount)])
async def read_forests(ctx: ContextObj = Depends(get_ctx)):
    """Returns all wildland forests as a list"""
    raise HTTPException(status_code=404, detail="Not Implemented")


@router.get("/forest/{name}", tags=["forest"])
async def read_forest(name: str):
    """Returns information of specific wildland forest"""
    raise HTTPException(status_code=404, detail="Not Implemented")
