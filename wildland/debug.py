# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Michał Haponiuk <mhaponiuk@wildland.io>,
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
Helpfull functions to start vscode debugger listener in the background.
"""


import os
from distutils.util import strtobool

import debugpy

PORT = 5678

def _is_debugpy_server_running() -> bool:
    return False

def start_debugpy_server_if_enabled() -> None:
    """
    Starts debugpy listener in the background.
    Can be blocking untill debugger attach -- see DEBUGPY environment vars
    """
    env_debugpy: bool = strtobool(os.environ.get("DEBUGPY", "False"))
    if env_debugpy:
        print(f"debugpy listen on port {PORT}",)
        debugpy.listen(("0.0.0.0", PORT))
        env_debugpy_wait: bool = strtobool(os.environ.get("DEBUGPY__WAIT", "False"))
        if env_debugpy_wait:
            print("waiting for vscode remote attach")
            debugpy.wait_for_client()
