from pytest import mark, fixture
from os import environ
from vpn_passthrough.pia import PIA, Credentials
from vpn_passthrough.openvpn import OpenVPN
from vpn_passthrough.network_namespace import NetworkNamespace


def require_pia_credentials():
    pia_user = environ.get("PIA_USER", None)
    pia_pass = environ.get("PIA_PASS", None)
    return mark.skipif(
        pia_user is None or pia_pass is None,
        reason=f"Credentials are required to connect to PIA"
    )


@fixture
def pia_credentials() -> Credentials:
    return Credentials(
        username=environ["PIA_USER"],
        password=environ["PIA_PASS"],
    )


@fixture
def pia(pia_credentials: Credentials) -> PIA:
    return PIA(
        credentials=pia_credentials,
    )


@fixture
def openvpn(pia_credentials: Credentials) -> OpenVPN:
    return OpenVPN()


@require_pia_credentials()
def test_list_regions(pia: PIA):
    regions = pia.list_regions()
    print(regions)
    assert len(regions) > 0


@require_pia_credentials()
def test_generate_token(pia: PIA):
    token = pia.generate_token()
    assert token is not None


@require_pia_credentials()
def test_generate_payload_and_signature(pia_credentials: Credentials, openvpn: OpenVPN):
    with NetworkNamespace(name="test_openvpn-test_port_forward") as network_namespace:
        with OpenVPN(network_namespace=network_namespace) as openvpn:
            pia = PIA(credentials=pia_credentials, network_namespace=network_namespace)
            gateway = openvpn.gateway
            payload_and_signature = pia.generate_payload_and_signature(
                gateway=gateway, 
                hostname="belgrade402",
            )

@require_pia_credentials()
def test_forward_port(pia_credentials: Credentials, openvpn: OpenVPN):
    with NetworkNamespace(name="test_openvpn-test_port_forward") as network_namespace:
        with OpenVPN(network_namespace=network_namespace) as openvpn:
            pia = PIA(credentials=pia_credentials, network_namespace=network_namespace)
            gateway = openvpn.gateway
            port = pia.forward_port(
                gateway=gateway, 
                hostname="belgrade402",
            )
            assert port > 0

            check_connectivity(
                
            )




