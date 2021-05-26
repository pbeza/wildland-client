from fastapi import APIRouter, Depends
from wildland.api.dependency import ContextObj, get_ctx
from wildland.manifest.manifest import WildlandObjectType

router = APIRouter()


@router.get("/user/", tags=["user"])
async def read_users(ctx: ContextObj = Depends(get_ctx)):
    users = ctx.client.load_all(WildlandObjectType.USER)
    return users


@router.get("/user/me", tags=["user"])
async def read_user_me():
    return {"username": "fakecurrentuser"}


@router.get("/user/{username}", tags=["user"])
async def read_user(username: str):
    return {"username": username}
