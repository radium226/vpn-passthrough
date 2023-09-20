from pytest import fixture, mark

from subprocess import run
from os import environ

from vpn_passthrough.network_namespace import NetworkNamespace
from vpn_passthrough.openvpn import OpenVPN
from vpn_passthrough.find_ip import find_ip
from vpn_passthrough.openvpn.script.script import ScriptServer


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
    

@mark.timeout(5)
def test_script():
    with ScriptServer() as script_server:
        run(["vpn-passthrough-openvpn-script"], env=environ | {
            "common_name": "belgrade402",
            "config": "serbia.ovpn",
            "daemon": "0",
            "daemon_log_redirect": "0",
            "daemon_pid": "561858",
            "daemon_start_time": "1695061312",
            "dev": "tun0",
            "dev_type": "tun",
            "foreign_option_1": "dhcp-option DNS 10.0.0.243",
            "ifconfig_local": "10.7.112.194",
            "ifconfig_netmask": "255.255.255.0",
            "proto_1": "udp",
            "remote_1": "rs.privacy.network",
            "remote_port_1": "1198",
            "route_net_gateway": "10.200.1.2",
            "route_vpn_gateway": "10.7.112.1",
            "script_context": "init",
            "script_type": "debug",
            "trusted_ip": "37.46.115.22",
            "trusted_port": "1198",
            "tun_mtu": "1500",
            "untrusted_ip": "37.46.115.22",
            "untrusted_port": "1198",
            "verb": "1",
            "NEW_NAMESERVER": "1.2.3.4",
        }, check=True)

        script_server.wait_for_debug()

