from pytest import raises
from vpn_passthrough.check_connectivity import check_connectivity

def test_success_over_loopback_device():
    check_connectivity(6543)


def test_failure_over_loopback_device():
    with raises(Exception):
        check_connectivity(
            local_port=6543,
            remote_port=3456,
        )