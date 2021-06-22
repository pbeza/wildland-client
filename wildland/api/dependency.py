# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Muhammed Tanrikulu <muhammed@wildland.io>
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

"""
Wildland Rest API Dependency module
"""

from pathlib import Path
import easywebdav
from wildland.client import Client

class ContextObj:
    """Helper object for keeping state in :attr:`click.Context.obj`"""

    def __init__(self, client: Client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session

# Dependency
def get_ctx():
    """Each api method can reach Wildland Client context through this dependency"""
    client = Client(dummy=False, base_dir=None)
    ctx = ContextObj(client)
    return ctx

def get_webdav():
    """Each api method can reach Webdav Client through this dependency"""
    easywebdav.client.basestring = (str, bytes)
    webdav = easywebdav.connect('localhost', port="8080")
    return webdav
