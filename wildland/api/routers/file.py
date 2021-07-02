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
Wildland File Rest API
"""

import io
import logging
import os
from pathlib import Path
from typing import Optional
from wildland.control_client import ControlClientError
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from PIL import Image
from wildland.api.dependency import ContextObj, get_ctx, get_webdav


router = APIRouter()
SUPPORTED_MIMETYPES = {
    "application/pdf": "PDF",
    "image/bmp": "BMP",
    "image/gif": "GIF",
    "image/jpeg": "JPEG",
    "image/vnd.microsoft.icon": "ICO",
    "image/image/x-icon": "ICO",
    "image/png": "PNG",
    "image/svg+xml": "SVG",
    "image/tiff": "TIFF",
    "image/webp": "WEBP",
}
logger = logging.getLogger("gunicorn.error")


@router.get("/file/", tags=["file"])
async def read_dir(
    _q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
    webdav=Depends(get_webdav),
):
    """Returns entries of given path"""
    files = webdav.ls(os.path.join("/", path))
    if len(files) > 0:
        del files[0]  # remove current directory
    return files


@router.get("/file/read/", tags=["file"])
async def read_file(
    _q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
    webdav=Depends(get_webdav),
):
    """Returns file from given path"""
    bio = io.BytesIO()
    webdav.download(os.path.join("/", path), bio)
    return Response(content=bio.getvalue())


@router.get("/file/thumbnail/", tags=["file"])
async def read_thumbnail(
    _q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
    webdav=Depends(get_webdav),
):
    """Generates and returns thumbnails of images from given path"""
    bio = io.BytesIO()
    webdav.download(os.path.join("/", path), bio)

    bio.seek(0)
    image = Image.open(bio)
    mimetype = image.get_format_mimetype()
    try:
        image.verify()  # if you need to load the image after using this method, you must reopen the image file. # pylint: disable=line-too-long
        bio.seek(0)
        image = Image.open(bio)
    except Exception:
        return "No thumbnail available."

    thumb_bytes = io.BytesIO()
    THUMBNAIL_SIZE = (128, 128)
    image.thumbnail(THUMBNAIL_SIZE, Image.ANTIALIAS)
    thumb_extension = SUPPORTED_MIMETYPES.get(mimetype, None)
    if not thumb_extension:
        return Response(
            content=f"Unsupported mimetype {mimetype}",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    image.save(thumb_bytes, thumb_extension)
    return Response(content=thumb_bytes.getvalue())

@router.get("/file/container", tags=["file, container"])
def find_container_by_path(
    ctx: ContextObj = Depends(get_ctx),
    _q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
):
    try:
        relative_path = Path(ctx.mount_dir).joinpath(path.strip("/"))
        logger.debug("relative_path", relative_path)
        results = set(ctx.fs_client.pathinfo(relative_path))
    except ControlClientError:
        results = []

    return results
