# pylint: disable=missing-docstring,redefined-outer-name

import tempfile
import shutil

import pytest

from ..manifest.sig import GpgSigContext

# The following fixtures are session-scoped for performance reasons (generating
# keys takes time).

@pytest.fixture(scope='session')
def gpg_sig():
    home_dir = tempfile.mkdtemp(prefix='wlgpg.')
    try:
        yield GpgSigContext(home_dir)
    finally:
        shutil.rmtree(home_dir)

@pytest.fixture(scope='session')
def signer(gpg_sig):
    keyid = gpg_sig.gen_test_key(name='Test 1', passphrase='secret')
    gpg_sig.add_signer(keyid)
    return keyid


@pytest.fixture(scope='session')
def other_signer(gpg_sig):
    keyid = gpg_sig.gen_test_key(name='Test 2', passphrase='secret')
    gpg_sig.add_signer(keyid)
    return keyid
