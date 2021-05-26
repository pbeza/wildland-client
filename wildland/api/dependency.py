from wildland.client import Client
import easywebdav

class ContextObj:
    """Helper object for keeping state in :attr:`click.Context.obj`"""

    def __init__(self, client: Client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session

# Dependency
def get_ctx():
    client = Client(dummy=False, base_dir=None)
    ctx = ContextObj(client)
    return ctx

def get_webdav():
    easywebdav.client.basestring = (str, bytes)
    webdav = easywebdav.connect('localhost', port="8080")
    return webdav