#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import errno
import os
import pathlib

from voluptuous import Schema, All, Coerce

from . import storage as _storage
from .fuse_utils import flags_to_mode, handler

__all__ = ['LocalStorage']

class LocalFile(_storage.AbstractFile):
    def __repr__(self):
        return f'<LocalFile storage={self.storage!r} relpath={self.path!r}>'

    @handler
    def __init__(self, fs, container, storage, path, flags, *args):
        super().__init__(fs, container, storage, path, flags, *args)
        self.path = path

        # pylint: disable=protected-access
        self.file = os.fdopen(
            os.open(self.storage._path(path), flags, *args),
            flags_to_mode(flags))

    @handler
    def release(self, _flags):
        return self.file.close()

    @handler
    def fgetattr(self):
        '''...

        Without this method, at least :meth:`read` does not work.
        '''
        return os.fstat(self.file.fileno())

    @handler
    def read(self, length, offset):
        self.file.seek(offset)
        return self.file.read(length)

    @handler
    def write(self, buf, offset):
        self.file.seek(offset)
        return self.file.write(buf)

    @handler
    def ftruncate(self, length):
        return self.file.truncate(length)

class LocalStorage(_storage.AbstractStorage):
    '''Local, file-based storage'''
    SCHEMA = Schema({
        # pylint: disable=no-value-for-parameter
        'type': 'local',
        'path': All(Coerce(pathlib.Path)),
    }, required=True)

    file_class = LocalFile

    def __init__(self, *, path, relative_to=None, **kwds):
        super().__init__(**kwds)
        path = pathlib.Path(path)
        if relative_to is not None:
            path = relative_to / path
        path = path.resolve()
        if not path.is_dir():
            raise OSError(errno.ENOENT,
                f'LocalStorage root does not exist: {path}')
        self.root = path

    def _path(self, path):
        ret = (self.root / path).resolve()
        ret.relative_to(self.root) # this will throw ValueError if not relative
        return ret

    def getattr(self, path):
        return os.lstat(self._path(path))

    def readdir(self, path):
        return os.listdir(self._path(path))

    def truncate(self, path, length):
        with open(self._path(path), 'ab') as file:
            file.truncate(length)
