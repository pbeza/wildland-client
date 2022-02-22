# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Piotr K. Isajew <pki@ex.com.pl>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Wildland storage backend using sshfs
"""

import getpass
from pathlib import PurePosixPath
from os import unlink
from tempfile import mkstemp
from subprocess import Popen, PIPE, STDOUT, run
from typing import List

import click

from wildland.fs_client import WildlandFSError
from wildland.manifest.schema import Schema
from wildland.log import get_logger
from wildland.storage_backends.base import StorageParam, StorageParamType
from .local_proxy import LocalProxy

logger = get_logger('storage-sshfs')


class SshFsBackend(LocalProxy):
    """
    sshfs backend
    """
    SCHEMA = Schema({
        "title": "SSHFS storage manifest",
        "type": "object",
        "required": ["host"],
        "properties": {
            "host": {
                "type": ["string"],
                "description": "Host name or IP address of SSH server to mount."
            },
            "login": {
                "type": ["string"],
                "description": "User login name on the SSH server."
            },
            "identity": {
                "type": ["string"],
                "description": "Private key to use during sshfs authentication."
            },
            "passwd": {
                "type": ["string"],
                "description": "Password to use during sshfs authentication."
            },
            "cmd": {
                "type": ["string"],
                "description": "Custom command to perform SSHFS mount."
            },
            "path": {
                "$ref": "/schemas/types.json#rel-path",
                "description": "A POSIX relative path to the directory on target server "
                               "that will be mounted as root.",
            },
            "mount-opts": {
                "type": ["string"],
                "description": "Additional mount options passed directly to sshfs command."
            },
        }
})
    TYPE='sshfs'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.sshfs_cmd = self.params['cmd']
        self.inner_mount_point = None
        self.sshfs_host = self.params['host']
        self.sshfs_path = self.params['path']
        self.mount_opts = self.params.get('mount_opts')
        self.login = self.params['login']
        self.passwd = self.params.get('passwd')
        self.identity = self.params.get('identity')

    ### Abstract method implementations
    def unmount_inner_fs(self, path: PurePosixPath) -> None:
        cmd = ["umount", str(path)]
        res = run(cmd, stderr=PIPE, check=True)
        if res.returncode != 0:
            logger.error("unable to unmount sshfs (%d)",
                         res.returncode)
        if len(res.stderr) > 0:
            logger.error(res.stderr.decode())


    def mount_inner_fs(self, path: PurePosixPath) -> None:
        cmd = [self.sshfs_cmd]
        if self.passwd:
            cmd.extend(['-o', 'password_stdin'])
        if self.identity:
            fd, ipath = mkstemp(text=True)
            with open(fd, 'w') as f:
                f.write(self.identity + '\n')
            cmd.extend(['-o', f'IdentityFile={ipath}'])

        if self.mount_opts:
            cmd.append(self.mount_opts)

        addr = self.sshfs_host
        if self.sshfs_path:
            addr += ':' + self.sshfs_path
        if self.login:
            addr = self.login + '@' + addr

        cmd.append(addr)
        cmd.append(str(path))

        try:
            with Popen(cmd, stdout=PIPE, stdin=PIPE, stderr=STDOUT) as executor:
                if self.passwd:
                    out, _ = executor.communicate(bytes(self.passwd, 'utf-8'))
                else:
                    out, _ = executor.communicate()
                if executor.returncode != 0:
                    logger.error("Failed to mount sshfs filesystem (%d)",
                                 executor.returncode)
                    if len(out.decode()) > 0:
                        logger.error(out.decode())
                        raise WildlandFSError("unable to mount sshfs")
        finally:
            if self.identity:
                unlink(ipath)

    @classmethod
    def storage_options(cls) -> List[StorageParam]:
        return [
            StorageParam('sshfs_command',
                         display_name='CMD',
                         default_value='sshfs',
                         required=True,
                         description='command to mount sshfs filesystem'
                         ),
            StorageParam('host',
                         display_name='HOST',
                         required=True,
                         description='host to mount'
                         ),
            StorageParam('path',
                         default_value='./',
                         description="path on target host to mount"
                         ),
            StorageParam('ssh_user',
                         display_name='USER',
                         default_value=getpass.getuser(),
                         description='user name to log on to target host'
                         ),
            StorageParam('ssh_identity',
                         display_name='PATH',
                         description='path to private key file to use for authentication'
                         ),
            StorageParam('pwprompt', param_type=StorageParamType.BOOLEAN,
                         description='prompt for password that will be used for authentication'
                         ),
            StorageParam('mount_options',
                         display_name='OPT1,OPT2,...',
                         description="additional options to be passed to sshfs command directly"
                         ),
        ]

    @classmethod
    def validate_and_parse_params(cls, params):
        data = {
            'cmd': params.get('sshfs_command'),
            'login': params.get('ssh_user'),
            'mount-opts': params.get('mount_options'),
            'host': params.get('host'),
            'path': params.get('path'),
            'passwd': params.get('passwd')
        }

        if params.get('ssh_identity'):
            with open(params['ssh_identity']) as f:
                data['identity'] = '\n'.join([l.rstrip() for l in f])

        data = cls.remove_non_required_params(data)

        cls.SCHEMA.validate(data)
        return data

    @classmethod
    def get_cli_user_input(cls, params):
        if params.get('ssh_identity') and params.get('pwprompt'):
            raise click.UsageError('pwprompt and ssh-identity are mutually exclusive')

        if params.get('pwprompt'):
            params['passwd'] = click.prompt('SSH password',
                                            hide_input=True)

        return params
