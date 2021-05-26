from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.manifest.manifest import WildlandObjectType

router = APIRouter()


@router.get("/container/", tags=["container"])
async def read_containers(ctx: ContextObj = Depends(get_ctx)):
    containers = ctx.client.load_all(WildlandObjectType.CONTAINER)
    return list(containers)


@router.get("/container/{name}", tags=["container"])
async def read_container(name: str):
    return {"name": name}
