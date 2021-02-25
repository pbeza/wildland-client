# An implementation of Wildland designed primarily for
# usage on Apple platform. Rather than assuming specific
# filesystem interface, like FUSE, we abstract out the
# needed functionality to an abstract driver, injected
# by hosting application, which provides the supported
# interface.

import logging
from .apple_log import apple_log

logger = logging.getLogger('fs')

class WildlandAbstractFS:
    '''
    An independent implementation of Wildland. Rather
    than assuming speficic filesystem driver (i.e. FUSE) 
    '''


    
    def start(self):
        apple_log.configure()
        logger.info('Wildland is starting')


def main():
    server = WildlandAbstractFS()
    server.start()

if __name__ == '__main__':
    main()
