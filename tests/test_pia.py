from pathlib import Path
from pytest import mark, fixture, fail
from os import environ
from vpn_passthrough.pia import PIA, Credentials
from vpn_passthrough.openvpn import OpenVPN
from vpn_passthrough.network_namespace import NetworkNamespace, NetworkNamespaceName
from vpn_passthrough.check_connectivity import check_connectivity
from vpn_passthrough.find_ip import find_ip


def require_pia_credentials():
    pia_user = environ.get("PIA_USER", None)
    pia_pass = environ.get("PIA_PASS", None)
    return mark.skipif(
        pia_user is None or pia_pass is None,
        reason=f"Credentials are required to connect to PIA"
    )


@fixture
def pia(pia_credentials: Credentials) -> PIA:
    return PIA(
        credentials=pia_credentials,
    )


@mark.requires_pia_credentials()
def test_list_regions(pia: PIA):
    regions = pia.list_regions()
    assert len(regions) > 0

    serbia_region = next((region for region in regions if region.name == "Serbia"), None)
    assert serbia_region is not None

    print(f"serbia_region={serbia_region}")
    


@mark.requires_pia_credentials()
def test_generate_token(pia: PIA):
    token = pia.generate_token()
    assert token is not None


@mark.requires_pia_credentials()
def test_generate_payload_and_signature(pia_credentials: Credentials):
    with NetworkNamespace(name=NetworkNamespaceName("test_openvpn-test_port_forward")) as network_namespace:
        with OpenVPN(
            network_namespace=network_namespace,
            config_file_path=Path(__file__).parent / "serbia.ovpn",
            remote="rs.privacy.network",
            port=1198,
            credentials=pia_credentials,
        ) as tunnel:
            pia = PIA(credentials=pia_credentials, network_namespace=network_namespace)
            gateway = tunnel.gateway
            payload_and_signature = pia.generate_payload_and_signature(
                gateway=gateway, 
                hostname="belgrade402",
            )

@mark.requires_pia_credentials()
def test_forward_port(pia_credentials: Credentials):
    with NetworkNamespace(name=NetworkNamespaceName("test_openvpn-test_port_forward")) as network_namespace:
        with OpenVPN(
            network_namespace=network_namespace,
            config_file_path=Path(__file__).parent / "serbia.ovpn",
            remote="rs.privacy.network",
            port=1198,
            credentials=pia_credentials,
        ) as tunnel:
            pia = PIA(credentials=pia_credentials, network_namespace=network_namespace)
            gateway = tunnel.gateway
            port = pia.forward_port(
                gateway=gateway, 
                hostname="belgrade402",
            )
            assert port > 0

            ip_address = find_ip(network_namespace=network_namespace)

            check_connectivity(
                local_port=port,
                remote_port=port,
                local_address="0.0.0.0",
                remote_address=ip_address,
                network_namespace=network_namespace,
            )



@mark.requires_pia_credentials()
def test_through_tunnel(pia_credentials: Credentials):
    with NetworkNamespace(name=NetworkNamespaceName("test_openvpn-test_port_forward")) as network_namespace:
        pia = PIA(
            credentials=pia_credentials,
            network_namespace=network_namespace,
        )
        with pia.through_tunnel(forward_port=True) as tunnel:
            if (forwarded_port := tunnel.forwared_port):
                ip_address = find_ip(network_namespace=network_namespace)
                check_connectivity(
                    local_port=forwarded_port,
                    remote_port=forwarded_port,
                    local_address="0.0.0.0",
                    remote_address=ip_address,
                    network_namespace=network_namespace,
                )
            else:
                fail("Unable to forward port! ")