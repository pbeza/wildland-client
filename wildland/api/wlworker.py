from uvicorn.workers import UvicornWorker

class WLUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {"root_path": "/api/0.0.1"}