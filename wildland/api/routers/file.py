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
import os
from pathlib import Path
from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from wildland.api.dependency import ContextObj, get_ctx, get_webdav, ensure_wl_mount
from wildland.api.utils import ProcessExecManager
from wildland.control_client import ControlClientError

exec_manager = ProcessExecManager()
router = APIRouter()
SUPPORTED_MIMETYPES = {
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
THUMBNAIL_SIZE = (96, 96)


@router.get("/file/", tags=["file"])
async def read_dir(
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
    path: str = "/",
    webdav=Depends(get_webdav),
):
    """Returns file from given path"""
    bio = io.BytesIO()
    webdav.download(os.path.join("/", path), bio)
    return Response(content=bio.getvalue())


def generate_thumbnail(webdav, path):
    """Generates and returns thumbnails of images from given path"""
    bio = io.BytesIO()

    try:
        webdav.download(os.path.join("/", path), bio)
    except Exception as exp:
        raise ConnectionError("Failed to download.") from exp

    bio.seek(0)
    try:
        image = Image.open(bio)
        mimetype = image.get_format_mimetype()
        thumb_extension = SUPPORTED_MIMETYPES.get(mimetype, None)
        assert thumb_extension
    except UnidentifiedImageError as exp:
        raise FileNotFoundError(f"Unsupported mimetype {str(exp)}") from exp
    try:
        # if you need to load the image after using image.verify()
        # method, you must reopen the image file.
        image.verify()
        bio.seek(0)
        image = Image.open(bio)
    except Exception as exp:
        raise FileNotFoundError("No thumbnail available.") from exp

    thumb_bytes = io.BytesIO()
    image.thumbnail(THUMBNAIL_SIZE, Image.BICUBIC)

    image.save(thumb_bytes, thumb_extension)
    image.close()
    return thumb_bytes


@router.get("/file/thumbnail/", tags=["file"])
async def read_thumbnail(
    path: str = "/",
    webdav=Depends(get_webdav),
):
    """Endpoint for generating image thumbnails"""
    try:
        executor = exec_manager.get_executor()
        thumb_bytes = await ProcessExecManager.run_in_process(
            executor, generate_thumbnail, webdav, path
        )
        return Response(content=thumb_bytes.getvalue())
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error)
        ) from error
    except ConnectionError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error)
        ) from error


@router.get(
    "/file/container", tags=["file, container"], dependencies=[Depends(ensure_wl_mount)]
)
def find_container_by_path(
    ctx: ContextObj = Depends(get_ctx),
    path: str = "/",
):
    """Finds container information for given file path and returns"""
    try:
        relative_path = Path(ctx.mount_dir).joinpath(path.strip("/"))
        results = set(ctx.fs_client.pathinfo(relative_path))
    except ControlClientError:
        results = set()

    return results


@router.on_event("startup")
def startup_event():
    """Create ProcessPoolExecutor"""
    exec_manager.create_executor()


@router.on_event("shutdown")
def on_shutdown():
    """Shutdown ProcessPoolExecutor"""
    exec_manager.shutdown()
