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
Wildland Rest API Dependency module
"""

import os
from pathlib import Path, PurePosixPath
import easywebdav
from fastapi import Depends, status, HTTPException
from wildland.client import Client
from wildland.exc import WildlandError


class ContextObj:
    """Helper object for keeping state in :attr:`click.Context.obj`"""

    def __init__(self, client: Client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session


# Dependency
def get_ctx():
    """Each api method can reach Wildland Client context through this dependency"""
    wl_base_dir = os.environ.get("WL_BASE_DIR")  # needs better way
    base_dir = PurePosixPath(wl_base_dir) if wl_base_dir else None
    client = Client(dummy=False, base_dir=base_dir)
    ctx = ContextObj(client)
    return ctx


def get_webdav():
    """Each api method can reach Webdav Client through this dependency"""
    easywebdav.client.basestring = (str, bytes)
    webdav = easywebdav.connect("localhost", port="8080")
    return webdav


def ensure_wl_mount(ctx: ContextObj = Depends(get_ctx)):
    """Some endpoints requires Wildland to be mounted, this dependency ensuring it"""
    try:
        ctx.fs_client.ensure_mounted()
    except WildlandError as wildland_error:
        raise HTTPException(
            detail="Wildland is not mounted",
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        ) from wildland_error
