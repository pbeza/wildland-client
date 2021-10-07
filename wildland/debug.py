import os
from distutils.util import strtobool

import debugpy

PORT = 5678

def is_debugpy_server_running() -> bool:
    return False

def start_debugpy_server_if_enabled() -> None:
    env_debugpy: bool = strtobool(os.environ.get("DEBUGPY", "False"))
    if env_debugpy:
        print(f"debugpy listen on port {PORT}",)
        debugpy.listen(("0.0.0.0", PORT))
        env_debugpy_wait: bool = strtobool(os.environ.get("DEBUGPY__WAIT", "False"))
        if env_debugpy_wait:
            print("waiting for vscode remote attach")
            debugpy.wait_for_client()
