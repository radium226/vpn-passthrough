from pytest import fixture, skip
from os import environ

from vpn_passthrough.commons import Credentials, User, Password


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_pia_credentials(): Ensure that the test will have PIA_USER and PIA_PASS environment variables set")


def pytest_runtest_setup(item):
    for mark in item.iter_markers(name="requires_pia_credentials"):
        if "PIA_USER" not in environ or "PIA_PASS" not in environ:
            skip("Test requires PIA_USER and PIA_PASS environment variables to be set")
            return
        
@fixture
def pia_credentials() -> Credentials:
    return Credentials(
        user=User(environ["PIA_USER"]),
        password=Password(environ["PIA_PASS"]),
    )