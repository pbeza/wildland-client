
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple
import os
from argparse import ArgumentParser
import asyncio
import logging
import errno
import sys

import fuse
import pyfuse3
import pyfuse3_asyncio

from .log import init_logging
from .storage_backends.base import StorageBackend
from .storage_backends.local import LocalStorageBackend
from .conflict import ConflictResolver
from .exc import WildlandError
from .fuse_utils import async_debug_handler

pyfuse3_asyncio.enable()
logger = logging.getLogger('fuse')


class WildlandFS(pyfuse3.Operations):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self):
        super().__init__()

        self.uid = os.getuid()
        self.gid = os.getgid()

        self.inode_path_map = {}
        self.path_inode_map = {}
        self.inode_counter = 0
        self.lookup_count = {}

        self.fh_map = {}

        self._add_path(pyfuse3.ROOT_INODE, PurePosixPath('/'))

        # Mount information
        self.storages: Dict[int, StorageBackend] = {}
        self.storage_paths: Dict[int, List[PurePosixPath]] = {}
        self.main_paths: Dict[PurePosixPath, int] = {}
        self.storage_counter = 0
        # self.mount_lock = threading.Lock()

        self.resolver = WildlandFSConflictResolver(self)

        backend = LocalStorageBackend(params={'type': 'local', 'path': '/tmp/storage'})
        self._mount_storage([PurePosixPath('/local')], backend)


    def _mount_storage(self, paths: List[PurePosixPath], storage: StorageBackend,
                      remount=False):
        '''
        Mount a storage under a set of paths.
        '''

        logger.info('Mounting storage %r under paths: %s',
                    storage, [str(p) for p in paths])

        main_path = paths[0]
        current_ident = self.main_paths.get(main_path)
        if current_ident is not None:
            if remount:
                logger.info('Unmounting current storage: %s, for main path: %s',
                             current_ident, main_path)
                self._unmount_storage(current_ident)
            else:
                raise WildlandError('Storage already mounted under main path: %s')

        ident = self.storage_counter
        self.storage_counter += 1

        storage.mount()

        self.storages[ident] = storage
        self.storage_paths[ident] = paths
        self.main_paths[main_path] = ident
        for path in paths:
            self.resolver.mount(path, ident)

        # self.control.clear_cache()

    def _unmount_storage(self, ident: int):
        '''Unmount a storage'''

        assert ident in self.storages
        assert ident in self.storage_paths
        storage = self.storages[ident]
        paths = self.storage_paths[ident]
        logger.info('Unmounting storage %r from paths: %s',
                     storage, [str(p) for p in paths])

        storage.unmount()

        # TODO check open files?
        del self.storages[ident]
        del self.storage_paths[ident]
        del self.main_paths[paths[0]]
        for path in paths:
            self.resolver.unmount(path, ident)

    def _path(self, inode):
        try:
            return self.inode_path_map[inode]
        except KeyError:
            raise pyfuse3.FUSEError(errno.ENOENT)

    def _add_path(self, inode, path):
        if inode in self.lookup_count:
            self.lookup_count[inode] += 1
            assert self.inode_path_map[inode] == path
            assert self.path_inode_map[path] == inode
        else:
            self.lookup_count[inode] = 1
            assert path not in self.inode_path_map
            self.inode_path_map[inode] = path
            self.path_inode_map[path] = inode

    def _remove_path(self, inode, path, nlookup=1):
        if self.lookup_count[inode] > nlookup:
            self.lookup_count[inode] -= nlookup
            return

        del self.lookup_count[inode]
        del self.inode_path_map[inode]
        del self.path_inode_map[path]

    def _proxy(self, method_name, path, *args,
              parent=False,
              modify=False,
              **kwargs):
        '''
        Proxy a call to corresponding Storage.

        If parent is true, resolve the path based on parent. This will apply
        for calls that create a file or otherwise modify the parent directory.

        If modify is true, this is an operation that should not be proxied to
        read-only storage.
        '''

        path = PurePosixPath(path)
        to_resolve = path.parent if parent else path

        _st, res = self.resolver.getattr_extended(to_resolve)
        if not res:
            raise pyfuse3.FUSEError(errno.EACCES)

        # with self.mount_lock:
        storage = self.storages[res.ident]

        if not hasattr(storage, method_name):
            raise pyfuse3.FUSEError(errno.ENOSYS)

        if modify and storage.read_only:
            raise pyfuse3.FUSEError(errno.EROFS)

        relpath = res.relpath / path.name if parent else res.relpath
        return getattr(storage, method_name)(relpath, *args, **kwargs)

    def _entry(self, st: fuse.Stat, inode: int):
        attr = pyfuse3.EntryAttributes()
        attr.st_mode = st.st_mode
        attr.st_size = st.st_size
        attr.st_nlink = st.st_nlink
        attr.st_atime_ns = st.st_atime*1000
        attr.st_ctime_ns = st.st_ctime*1000
        attr.st_mtime_ns = st.st_mtime*1000
        attr.st_gid = self.gid
        attr.st_uid = self.uid
        attr.st_ino = inode
        return attr

    # FUSE handlers

    @async_debug_handler
    async def forget(self, inode_list):
        logger.debug('forget %s', inode_list)
        for (inode, nlookup) in inode_list:
            path = self.inode_path_map[inode]
            self._remove_path(inode, path, nlookup)

    @async_debug_handler
    async def getattr(self, inode, ctx=None):
        path = self._path(inode)

        return await self._getattr(path, inode)

    async def _getattr(self, path, inode=None):
        st, res = self.resolver.getattr_extended(path)
        attr = self._entry(st, inode)
        if not res:
            #import pdb; pdb.set_trace()
            return attr

        storage = self.storages[res.ident]
        if storage.read_only:
            attr.st_mode &= ~0o222
        return attr

    @async_debug_handler
    async def lookup(self, parent_inode, name, ctx=None):
        name = name.decode('utf8') # TODO

        logger.info('lookup %s %s', parent_inode, name)
        path = self._path(parent_inode) / name
        inode = self.path_inode_map.get(path)

        if name in ['.', '..']:
            assert path in self.path_inode_map
            return await self._getattr(path, inode)

        if inode is None:
            inode = self.inode_counter
            self.inode_counter += 1

        self._add_path(inode, path)
        try:
            return await self._getattr(path, inode)
        except:
            self._remove_path(inode, path)
            raise

    @async_debug_handler
    async def opendir(self, inode, ctx):
        logger.debug('opendir')
        return inode

    @async_debug_handler
    async def readdir(self, fh, start_id, token):
        logger.debug('readdir')
        inode = fh
        path = self._path(inode)
        names = self.resolver.readdir(path)
        entries = []
        for name in names:
            file_path = path / name
            file_inode = self.path_inode_map.get(file_path, 0)
            attr = await self._getattr(file_path, file_inode)
            entries.append((name, attr))

        logger.debug('read %d entries, starting at %d', len(entries), start_id)
        # Sort entries without inode last
        entries.sort(key=lambda e: (e[1].st_ino if e[1].st_ino == 0 else sys.maxsize))

        for name, attr in sorted(entries):
            if attr.st_ino == 0:
                assert attr.st_ino >= start_id
                attr.st_ino = self.inode_counter
                self.inode_counter += 1
            self._add_path(attr.st_ino, path / name)
            if attr.st_ino < start_id:
                self._remove_path(attr.st_ino, path / name)
                continue

            if not pyfuse3.readdir_reply(token, name.encode('utf8'), attr, attr.st_ino + 1):
                self._remove_path(attr.st_ino, path / name)
                break

    @async_debug_handler
    async def open(self, inode, flags, ctx):
        path = self._path(inode)
        modify = bool(flags & (os.O_RDWR | os.O_WRONLY))
        f = self._proxy('open', path, flags, modify=modify)

        fh = len(self.fh_map)
        self.fh_map[fh] = f
        fi = pyfuse3.FileInfo()
        fi.fh = fh
        fi.direct_io = True # TODO only if necessary
        return fi

    @async_debug_handler
    async def read(self, fh, off, size):
        f = self.fh_map[fh]
        return f.read(size, off)

    @async_debug_handler
    async def release(self, fh):
        f = self.fh_map[fh]
        del self.fh_map[fh]
        f.release(0)


class WildlandFSConflictResolver(ConflictResolver):
    '''
    WildlandFS adapter for ConflictResolver.
    '''

    def __init__(self, fs: WildlandFS):
        super().__init__()
        self.fs = fs

    def storage_getattr(self, ident: int, relpath: PurePosixPath) -> fuse.Stat:
        storage = self.fs.storages[ident]
        return storage.getattr(relpath)

    def storage_readdir(self, ident: int, relpath: PurePosixPath) -> fuse.Stat:
        storage = self.fs.storages[ident]
        return storage.readdir(relpath)


def parse_args():
    '''Parse command line'''

    parser = ArgumentParser()

    parser.add_argument('mountpoint', type=str,
                        help='Where to mount the file system')
    parser.add_argument('--debug-fuse', action='store_true', default=False,
                        help='Enable FUSE debugging output')
    parser.add_argument('--log', metavar='PATH',
                        help='path to log file, use - for stderr')
    return parser.parse_args()


def main():
    '''FUE driver entry point'''

    args = parse_args()
    if args.log == '-':
        init_logging(console=True)
    else:
        init_logging(console=False, file_path=args.log)

    fs = WildlandFS()
    fuse_options = set(pyfuse3.default_options)
    fuse_options.add('fsname=wildland')
    if args.debug_fuse:
        fuse_options.add('debug')

    pyfuse3.init(fs, args.mountpoint, fuse_options)
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(pyfuse3.main())
    except:
        pyfuse3.close()
        raise
    finally:
        loop.close()

    pyfuse3.close()


if __name__ == '__main__':
    main()
