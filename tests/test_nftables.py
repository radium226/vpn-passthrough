from ipaddress import IPv4Address
from vpn_passthrough.nftables import nftables


@nftables(debug=True)
def debug_file(ip_addr: IPv4Address) -> None:
    ...


@nftables(debug=True)
def debug_doc(ip_addr: IPv4Address) -> None:
    """The ip_addr is {ip_addr}"""

@nftables()
def check_nftables():
    """
    table inet nat {
        chain prerouting {
            type nat hook prerouting priority dstnat; policy accept;
        }
        chain postrouting {
            type nat hook postrouting priority srcnat; policy accept;
            masquerade random
        }
    }
    """


def test_nftables_based_on_file():
    debug_file(ip_addr=IPv4Address("127.0.0.1"))


def test_nfttables_based_on_doc():
    debug_doc(ip_addr=IPv4Address("127.0.0.1"))

def test_nftables_with_check():
    check_nftables(check=True)