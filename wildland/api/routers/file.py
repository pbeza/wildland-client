import io
import json
import os
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from PIL import Image
from typing import Optional
from wildland.api.dependency import ContextObj, get_webdav


router = APIRouter()


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
    image = Image.open(bio)
    bio.seek(0)
    bio.truncate()
    
    try:
        image.verify()
    except Exception:
        return "No thumbnail available."
    
    image.thumbnail((128, 128))
    image.save(bio)
    return Response(content=bio.getvalue())
