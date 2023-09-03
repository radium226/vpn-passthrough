from pytest import fixture

from vpn_passthrough.network_namespace import NetworkNamespace
from vpn_passthrough.openvpn import OpenVPN
from vpn_passthrough.find_ip import find_ip


@fixture
def network_namespace():
    with NetworkNamespace("test_openvpn") as network_namespace:
        yield network_namespace


def test_openvpn(network_namespace: NetworkNamespace):
    public_ip_1 = find_ip(network_namespace=network_namespace)
    with OpenVPN(network_namespace=network_namespace):
        private_ip = find_ip(network_namespace=network_namespace)
        assert private_ip != public_ip_1

    public_ip_2 = find_ip(network_namespace=network_namespace)
    assert public_ip_1 == public_ip_2
    




