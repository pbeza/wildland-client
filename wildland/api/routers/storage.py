import logging
from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()
logger = logging.getLogger("gunicorn.error")


@router.get("/storage/", tags=["storage"])
async def read_storages(ctx: ContextObj = Depends(get_ctx)):
    storages = ctx.client.load_all(WildlandObject.Type.STORAGE)
    logger.info(list(storages))

    backend_list = []
    for container in  ctx.client.load_all(WildlandObject.Type.CONTAINER):
        for backend in container.manifest._fields.get("backends", {}).get("storage", []):
            if not backend:
                continue

            if not isinstance(backend, str):
                backend_list.append(backend)

            
    
    return list(storages) + backend_list


@router.get("/storage/{name}", tags=["storage"])
async def read_storage(name: str):
    return {"name": name}
