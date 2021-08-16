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
from base64 import b64decode
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from requests.exceptions import ConnectionError

from wildland.api.main import api_with_version
from wildland.ipc import EventIPC


MESSAGE_FAILED_TO_DOWNLOAD = {"detail": "Failed to download."}
MESSAGE_NO_THUMBNAIL = {"detail": "No thumbnail available."}
MESSAGE_NOT_MOUNTED = {"detail": "Wildland is not mounted"}
MESSAGE_NOT_IMPLEMENTED = {"detail": "Not Implemented"}
MESSAGE_UNSUPPORTED_MIMETYPE = {"detail": "Unsupported mimetype"}
PX128_IMG64 = "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAABU" \
"0lEQVR4nOzTwQnCQABEUZGtxJNt2IAtWI9gixJIF8kpRezhEfJfBQOfGb/Pcjuz" \
"1/bVE6bc9YCrKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgC" \
"sAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVAC" \
"sAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXAx" \
"v+x6w1T3s9VT5jSA7ACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGw" \
"AmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKw" \
"AWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKw" \
"BWAOwIAAD//5psB+MfT8zoAAAAAElFTkSuQmCC"
PDF_BASE64 = "JVBERi0xLg10cmFpbGVyPDwvUm9vdDw8L1BhZ2VzPDwvS2lkc1" \
"s8PC9NZWRpYUJveFswIDAgMyAzXT4+XT4+Pj4+Pg=="

api_client = TestClient(api_with_version)


class WebDAV:
    '''Mock for WebDAV Client'''
    def __init__(self, host: str, port: str):
        pass

    @staticmethod
    def ls(_path):
        return ["/"]

    @staticmethod
    def download(path: str, bio: bytes):
        if path == "/path/to/img.png":
            img_bytes = b64decode(PX128_IMG64)
            bio.write(img_bytes)
        if path == "path/to/unsupported.pdf":
            pdf_bytes = b64decode(PDF_BASE64)
            bio.write(pdf_bytes)
        if path == "/path/to/fail.png":
            raise Exception("nooo I failed so hard")
        return b''

class mockPIL:
    '''Mock for PIL Image class'''
    def __init__(self, bio: bytes):
        pass

    def close(self):
        pass

    @staticmethod
    def get_format_mimetype():
        return "image/png"

    def save(self, bio, format):
        pass

    def thumbnail(self):
        pass

    @staticmethod
    def verify():
        raise Exception("verification failed")

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


def test_bridge_list(cli):
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


def test_container_list(cli):
    time.sleep(2)
    cli("user", "create", "Gryphon", "--key", "0xaaa")
    cli("container", "create", "Container", "--path", "/PATH")
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


@patch("easywebdav.connect", WebDAV)
def test_file_list(cli):

    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file")
    assert response.status_code == 200

    file_list = response.json()
    assert file_list == []


@patch("easywebdav.connect", WebDAV)
def test_file_container_info(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file/container")
    assert response.status_code == 200

    container_information = response.json()
    assert container_information == []


@patch("easywebdav.connect", WebDAV)
def test_file_content(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file/read")
    assert response.status_code == 200

    file = response.content
    assert file == b''


@patch("easywebdav.connect", WebDAV)
def test_file_thumbnail(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file/thumbnail?path=/path/to/img.png")
    assert response.status_code == 200

    file = response.content
    image = Image.open(BytesIO(file))
    width, height = image.size

    assert width >= 96 and height >= 96


@patch("easywebdav.connect", WebDAV)
def test_file_thumbnail_fail(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file/thumbnail?path=/path/to/fail.png")
    assert response.status_code == 500
    assert response.json() == MESSAGE_FAILED_TO_DOWNLOAD

@patch("easywebdav.connect", WebDAV)
def test_file_thumbnail_unsupported(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file/thumbnail?path=/path/to/unsupported.pdf")
    assert response.status_code == 415

    result = response.json()
    assert result.get('detail').startswith(
        MESSAGE_UNSUPPORTED_MIMETYPE.get('detail')
    )


@patch("easywebdav.connect", WebDAV)
@patch("PIL.Image.open", mockPIL)
def test_file_thumbnail_broken(cli):
    time.sleep(2)
    cli("user", "create", "Lory", "--key", "0xbbb")
    cli("start", "--default-user", "Lory")

    response = api_client.get("/file/thumbnail?path=/path/to/img.png")
    assert response.status_code == 415
    assert response.json() == MESSAGE_NO_THUMBNAIL


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
