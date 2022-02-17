# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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

# pylint: disable=missing-docstring

import pytest

import wildland.core.core_utils as core_utils
from wildland.client import Client
from wildland.core.wildland_core import WildlandCore
from wildland.wildland_object.wildland_object import WildlandObject

# pylint: disable=missing-docstring,redefined-outer-name


@pytest.fixture
def setup(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/path')


# pylint: disable=unused-argument
@pytest.fixture
def wlcore(setup, base_dir):
    _client = Client(base_dir=base_dir)
    return WildlandCore(_client)


def test_create_local_storage(wlcore, base_dir):
    container = wlcore.client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')
    wl_container = core_utils.container_to_wlcontainer(container, wlcore.client)

    result = wlcore.storage_create('local', {'location': str(base_dir / 'storage1')},
                                   wl_container.id, 'Storage1')
    assert result[0].success
    assert result[1] is not None
