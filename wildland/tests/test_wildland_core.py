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
from wildland.cli.cli_base import CliStorageUserInteraction
from wildland.client import Client
from wildland.core.wildland_core import WildlandCore
from wildland.core.wildland_objects_api import WLStorageBackend
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

    user_interaction_cls = CliStorageUserInteraction

    result = wlcore.storage_create('local', {'location': str(base_dir / 'storage1')},
                                   wl_container.id, user_interaction_cls, 'Storage1')
    assert result[0].success
    assert result[1] is not None


def test_supported_storage_backends(wlcore, base_dir):
    result, storage_backends = wlcore.supported_storage_backends()

    s3_backend = WLStorageBackend(
        description='Storage manifest (S3)',
        name='s3',
        required_fields=['s3_url', 'credentials'],
        supported_fields_with_description={
            's3_url': 'S3 URL, in the s3://bucket/path format',
            'endpoint_url': 'Override default AWS S3 URL with the given URL.',
            'credentials': None,
            'with-index': 'Maintain index.html files with directory listings (default: False)',
            'manifest-pattern': None
        }
    )
    dropbox_backend = WLStorageBackend(
        name='dropbox',
        description='Dropbox storage manifest',
        supported_fields_with_description={
            'location': "Absolute POSIX path acting as a root directory in user's dropbox",
            'token': 'Dropbox OAuth 2.0 access token. You can generate it in Dropbox App Console. '
                     'Deprecated and will be replaced in favor of App Key and refresh token.',
            'app-key': 'Dropbox App Key. You can obtain it in Dropbox App Console.',
            'refresh-token': "Dropbox OAuth 2.0 refresh token. "
                             "You can generate it using the following "
                             "https://www.dropbox.com/developers/documentation/http/documentation "
                             "at '/oauth2/token' endpoint section. Please note that this is "
                             "optional as the procedure is performed when a storage is created.",
            'manifest-pattern': None
        },
        required_fields=['token', 'app-key']
    )
    assert result.success
    assert len(storage_backends) == 26
    assert s3_backend in storage_backends
    assert dropbox_backend in storage_backends
