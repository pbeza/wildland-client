from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.wildland_object.wildland_object import WildlandObject

router = APIRouter()


@router.get("/container/", tags=["container"])
async def read_containers(ctx: ContextObj = Depends(get_ctx)):
    containers = ctx.client.load_all(WildlandObject.Type.CONTAINER)
    container_list = []
    for container in containers:
        container_obj = container.__dict__
        del container_obj['client'] 
        container_list.append(container_obj)
    return container_list


@router.get("/container/{name}", tags=["container"])
async def read_container(name: str):
    return {"name": name}
