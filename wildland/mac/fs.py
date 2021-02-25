# An implementation of Wildland designed primarily for
# usage on Apple platform. Rather than assuming specific
# filesystem interface, like FUSE, we abstract out the
# needed functionality to an abstract driver, injected
# by hosting application, which provides the supported
# interface.

import os
import logging
import threading
from pathlib import Path
from .apple_log import apple_log
from ..control_server import ControlServer, ControlHandler, control_command
from ..manifest.schema import Schema

logger = logging.getLogger('fs')

class WildlandAbstractFS:
    '''
    An independent implementation of Wildland. Rather
    than assuming speficic filesystem driver (i.e. FUSE) 
    '''

    def __init__(self, socket_path):
        # Mount information
        self.storages: Dict[int, StorageBackend] = {}
        self.storage_extra: Dict[int, Dict] = {}
        self.storage_paths: Dict[int, List[PurePosixPath]] = {}
        self.main_paths: Dict[PurePosixPath, int] = {}
        self.storage_counter = 1
        self.multithreaded = True
        self.mount_lock = threading.Lock()

        self.control_server = ControlServer()
        self.control_server.register_commands(self)
        self.default_user = None
        self.uid = None
        self.gid = None
        self.socket_path = Path(socket_path)
        command_schemas = Schema.load_dict('commands.json', 'args')
        self.control_server.register_validators({
            cmd: schema.validate for cmd, schema in command_schemas.items()
        })
    
    def start(self):
        apple_log.configure()
        self.uid, self.gid = os.getuid(), os.getgid()
        logger.info('Wildland is starting, control socket: %s',
                        self.socket_path)
        self.control_server.start(self.socket_path)

    @control_command('status')
    def control_status(self, _handler):
        """
        Status of the control client, returns a dict with parameters; currently only
        supports default (default_user)
        """
        logger.debug('got control command: status')
        result = dict()
        result['default-user'] = self.default_user
        return result

def main():
    server = WildlandAbstractFS()
    server.start()

if __name__ == '__main__':
    main()
