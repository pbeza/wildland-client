from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.manifest.manifest import WildlandObjectType

router = APIRouter()


@router.get("/bridge/", tags=["bridge"])
async def read_bridges(ctx: ContextObj = Depends(get_ctx)):
    bridges = ctx.client.load_all(WildlandObjectType.BRIDGE)
    return list(bridges)


@router.get("/bridge/{name}", tags=["bridge"])
async def read_bridge(name: str):
    return {"name": name}
