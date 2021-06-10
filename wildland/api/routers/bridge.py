import logging
from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()
logger = logging.getLogger("gunicorn.error")


@router.get("/bridge/", tags=["bridge"])
async def read_bridges(ctx: ContextObj = Depends(get_ctx)):
    bridges = ctx.client.load_all(WildlandObject.Type.BRIDGE)
    bridge_list = []
    for bridge in bridges:
        bridge_obj = bridge.__dict__
        del bridge_obj['client'] 
        bridge_list.append(bridge_obj)
    
    logger.info(bridge_list)
    return bridge_list


@router.get("/bridge/{name}", tags=["bridge"])
async def read_bridge(name: str):
    return {"name": name}
