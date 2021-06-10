import io
import os
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from PIL import Image
from typing import Optional
from wildland.api.dependency import get_webdav


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


@router.get("/file/", tags=["file"])
async def read_dir(
    q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
    webdav=Depends(get_webdav),
):
    files = webdav.ls(os.path.join("/", path))
    if len(files) > 0:
        del files[0]  # remove current directory
    return files


@router.get("/file/read/", tags=["file"])
async def read_file(
    q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
    webdav=Depends(get_webdav),
):
    bio = io.BytesIO()
    webdav.download(os.path.join("/", path), bio)
    return Response(content=bio.getvalue())


@router.get("/file/thumbnail/", tags=["file"])
async def read_file(
    q: Optional[str] = Query(None, title="Path Query"),
    path: str = "/",
    webdav=Depends(get_webdav),
):
    bio = io.BytesIO()
    webdav.download(os.path.join("/", path), bio)

    bio.seek(0)
    image = Image.open(bio)
    mimetype = image.get_format_mimetype()
    try:
        image.verify()  # if you need to load the image after using this method, you must reopen the image file.
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
