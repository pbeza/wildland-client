import pytest

import wildland.core.core_utils as core_utils
from wildland.client import Client
from wildland.core.wildland_core import WildlandCore
from wildland.wildland_object.wildland_object import WildlandObject


# pylint: disable=missing-docstring


@pytest.fixture
def setup(base_dir, cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/path')


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
