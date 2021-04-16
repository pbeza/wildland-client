# An implementation of Wildland designed primarily for
# usage on Apple platform. Rather than assuming specific
# filesystem interface, like FUSE, we abstract out the
# needed functionality to an abstract driver, injected
# by hosting application, which provides the supported
# interface.

'''
Wildland Filesystem implementation intendet to work as
part of embedded Python installation. This class is
primarily used within the specialized NFS server.
'''

import logging
import os
from pathlib import Path, PurePosixPath
from typing import List, Dict, Tuple, Optional
from .apple_log import apple_log
from ..fs_base import WildlandFSBase
from ..client import Client
from ..container import Container
from ..storage import StorageBackend, Storage
from ..user import User
from ..wlpath import WildlandPath
from ..fs_client import WildlandFSClient

logger = logging.getLogger('fs')

class WildlandMacFS(WildlandFSBase):
    '''
    A macOS implementation of Wildland. This is designed
    to provide services for wildland client macOS daemon
    NFS server and control service facilities.
    '''

    def __init__(self, socket_path):
        super().__init__()
        self.socket_path = Path(socket_path)
        self.client = None

    def start(self):
        '''
        Called to start file system operation.
        '''
        apple_log.configure()
        self.uid, self.gid = os.getuid(), os.getgid()
        logger.info('Wildland is starting, control socket: %s',
                        self.socket_path)
        self.control_server.start(self.socket_path)
        self.client = Client()

    def list_containers(self) -> List[Container]:
        logger.debug('list conatiners called')

        self.client.recognize_users()

        return list(self.client.load_containers())

    def list_users(self) -> List[Dict]:
        logger.debug('list_users called')
        rv = list()
        for user in self.client.load_users():
            u = dict()
            u['owner'] = user.owner
            u['path'] = str(user.paths[0])
            rv.append(u)
        return rv


    def _prepare_mount(self, container: Container, subcontainer_of: Optional[Container]):
        subcontainers = list(self.client.all_subcontainers(container))
        storages = self.client.get_storages_to_mount(container)
        yield (container, storages, ['/'], subcontainer_of)
        storage = self.client.select_storage(container)
        for subcontainer in subcontainers:
            yield from self.prepare_mount(subcontainer, container)

    def mount_containers(self, path):
        '''
        Mount container (and its subcontainers) reachable at given WildlandPath
        '''
        # shrunk down version of cli_container.mount
        self.client.recognize_users()
        params: List[Tuple[Container, List[Storage], List[PurePosixPath], Container]] = []

        try:
            if WildlandPath.match(path):

                for container in self.client.load_container_from_wlpath(WildlandPath.from_str(path)):
                    user_paths = self.client.get_bridge_paths_for_user(container.owner)
                    storages = self.client.get_storages_to_mount(container)
                
                    params.extend(self._prepare_mount(container, None))
                # TODO: use dynamic mount path
                fs_client = WildlandFSClient('/Volumes/wildland', self.socket_path)
                fs_client.mount_multiple_containers(params)
            else:
               logger.error('mount_containers: expected valid container path but got %s', path)
        except:
            logger.exception('mount_containers failure during mount containers')
