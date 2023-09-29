from vpn_passthrough.sudo import sudo
from getpass import getuser


@sudo()
def who_am_i():
    user = getuser()
    return user


def test_sudo():
    user = who_am_i()
    assert user == "root"