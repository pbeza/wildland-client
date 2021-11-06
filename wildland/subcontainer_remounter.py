import time
from wildland.wildland_object.wildland_object import WildlandObject
from wildland.fs_client import WildlandFSClient
from wildland.client import Client
from .storage_backends.base import StorageBackend
from wildland.log import get_logger

logger = get_logger('subcontainer_remounter')

class SubcontainerRemounter:
    """
    """
    
    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 container: WildlandObject.Type.CONTAINER):
        self.container = container
        self.client = client
        self.fs_client = fs_client
        self.backends = {}
        
        storages = self.client.get_storages_to_mount(container)
        for storage in storages:
            backend = StorageBackend.from_params(storage.params, deduplicate=True)
            get_children = backend.get_children(client = self.client)
            self.backends[backend] = get_children
        

    def run(self):
        """
        The main loop used for checking whether the container has any
        new children to be mounted
        """
                
        while True:
            for backend in self.backends.keys():
                initial_children = [(path, child) for path, child in self.backends[backend]]
                initial_paths = [path for path, child in initial_children]
                new_children = [(path, child) for path, child in backend.get_children(client = self.client)]
                new_paths = [path for path, child in new_children]
                
                if not initial_paths == new_paths:
                    to_mount = [(path, container) for path, container in new_children if path not in initial_children]
                    for tuple in to_mount:
                        user_paths = self.client.get_bridge_paths_for_user(self.container.owner)
                        container = tuple[1].get_container(self.container)
                        storages = self.client.get_storages_to_mount(container)
                        self.fs_client.mount_container(container = container,
                                                       storages = storages,
                                                       user_paths = user_paths,
                                                       subcontainer_of = self.container,
                                                       remount = True)


                self.backends[backend] = new_children
                time.sleep(10)
                    
