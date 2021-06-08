from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()


@router.get("/storage/", tags=["storage"])
async def read_storages(ctx: ContextObj = Depends(get_ctx)):
    storages = ctx.client.load_all(WildlandObject.Type.STORAGE)

    backends = []
    for container in  ctx.client.load_all(WildlandObject.Type.CONTAINER):
        for backend in container.backends:
            if not isinstance(backend, str):
                backends.append(backend)
        if not backends:
            continue
    
    return list(storages) + list(backends)


@router.get("/storage/{name}", tags=["storage"])
async def read_storage(name: str):
    return {"name": name}
