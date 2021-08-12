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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=missing-docstring,redefined-builtin, not-context-manager

import threading
import time

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import ConnectionError

from wildland.api.main import api_with_version
from wildland.ipc import EventIPC


MESSAGE_NOT_MOUNTED = {"detail": "Wildland is not mounted"}
MESSAGE_NOT_IMPLEMENTED = {"detail": "Not Implemented"}

api_client = TestClient(api_with_version)


def test_root():
    response = api_client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "message": f"Welcome to Wildland API! \
To get more information about endpoints, have a glance over \
'{api_with_version.root_path}/docs' path."
    }


def test_bridge_no_wl():
    response = api_client.get("/bridge")
    assert response.status_code == 200
    assert response.json() == []


def test_container_no_wl():
    response = api_client.get("/container")
    assert response.status_code == 428
    assert response.json() == MESSAGE_NOT_MOUNTED


def test_file_no_wl():
    with pytest.raises(ConnectionError):
        api_client.get("/file?path=/")


def test_forest_no_wl():
    response = api_client.get("/forest")
    assert response.status_code == 428
    assert response.json() == MESSAGE_NOT_MOUNTED


def test_storage_no_wl():
    response = api_client.get("/storage")
    assert response.status_code == 200
    assert response.json() == []


def test_user_no_wl():
    response = api_client.get("/user")
    assert response.status_code == 428
    assert response.json() == MESSAGE_NOT_MOUNTED


def test_bridge_list(cli, base_dir):
    cli("user", "create", "Pat", "--key", "0xbbb")
    cli("user", "create", "RefUser", "--key", "0xbbb", "--path", "/OriginalPath")
    cli(
        "bridge",
        "create",
        "Bridge",
        "--target-user",
        "RefUser",
        "--target-user-location",
        "https://example.com/RefUser.yaml",
        "--path",
        "/ModifiedPath",
    )

    response = api_client.get("/bridge")
    assert response.status_code == 200

    bridge_list = response.json()
    user = bridge_list[0]["user"] if bridge_list else None
    assert user == "https://example.com/RefUser.yaml"


def test_container_list(cli, base_dir):
    time.sleep(2)
    cli("user", "create", "Gryphon", "--key", "0xaaa")
    cli("container", "create", "Container", "--path", "/PATH")
    cli("start", "--default-user", "Gryphon")

    response = api_client.get("/container")
    assert response.status_code == 200

    container_list = response.json()
    owner = container_list[0]["owner"] if container_list else None
    assert owner == "0xaaa"


# @pytest.mark.timeout(10, method='thread')
@pytest.mark.skip(reason="TODO: Fix, IPC does not read on test")
def test_event_ws():
    def emit_event():
        time.sleep(2)
        ipc = EventIPC(True)
        ipc.emit("EMIT", "WL_TEST")

    wl_in_thread = threading.Thread(target=emit_event)

    with api_client.websocket_connect("/stream") as websocket:
        wl_in_thread.start()
        data = websocket.receive_json()
        assert data == {"topic": "EMIT", "label": "WL_TEST"}


@pytest.mark.skip(reason="WebDAV connection needs to be mocked")
def test_file_list(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file")
    assert response.status_code == 200

    file_list = response.json()
    assert file_list == []


@pytest.mark.skip(reason="WebDAV connection needs to be mocked")
def test_file_container_info():
    pass


@pytest.mark.skip(reason="WebDAV connection needs to be mocked")
def test_file_content():
    pass


@pytest.mark.skip(reason="WebDAV connection needs to be mocked")
def test_file_thumbnail():
    pass


def test_storage_list(cli):
    time.sleep(2)
    cli("user", "create", "Duck", "--key", "0xaaa")
    cli(
        "container",
        "create",
        "Container",
        "--path",
        "/riddle",
        "--no-encrypt-manifest",
    )
    cli(
        "storage",
        "create",
        "local",
        "Storage",
        "--location",
        "/riddle",
        "--container",
        "Container",
    )

    response = api_client.get("/storage")
    assert response.status_code == 200

    storage_list = response.json()
    location = storage_list[0]["location"] if storage_list else None
    assert location == "/riddle"


def test_user_list(cli):
    time.sleep(2)
    cli("user", "create", "Eaglet", "--key", "0xbbb")
    cli("start", "--default-user", "Eaglet")

    response = api_client.get("/user")
    assert response.status_code == 200

    user_list = response.json()
    owner = user_list[0]["owner"] if user_list else None
    assert owner == "0xbbb"


# NOT IMPLEMENTED ENDPOINTS
def test_specific_bridge():
    response = api_client.get("/bridge/wl")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED


def test_specific_container():
    response = api_client.get("/container/wl")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED


def test_forest_list(cli):
    time.sleep(2)
    cli("user", "create", "Duchess", "--key", "0xbbb")
    cli("start", "--default-user", "Duchess")

    response = api_client.get("/forest")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED


def test_specific_forest():
    response = api_client.get("/forest/wl")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED


def test_specific_storage():
    response = api_client.get("/storage/wl")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED


def test_default_user():
    response = api_client.get("/user/me")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED


def test_specific_user():
    response = api_client.get("/user/wl")
    assert response.status_code == 404
    assert response.json() == MESSAGE_NOT_IMPLEMENTED
