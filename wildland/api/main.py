from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from wildland.api.routers import bridge, container, storage, user, file

app = FastAPI(
    title="Wildland API",
    description="The Rest API made for Wildland Graphical User Interface",
    version="0.0.1-alpha.0",
)  # dependencies=[Depends(get_query_token)]

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bridge.router)
app.include_router(container.router)
app.include_router(storage.router)
app.include_router(user.router)
app.include_router(file.router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to Wildland API! To get more information about endpoints, have a glance over '/docs' path."
    }
