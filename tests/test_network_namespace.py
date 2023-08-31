from vpn_passthrough.network_namespace import NetworkNamespace, list_network_namespaces
from time import sleep

def test_network_namespace():
    number_of_network_namespaces = len(list_network_namespaces())
    
    with NetworkNamespace(name="test") as network_namespace:
        assert len(list_network_namespaces()) == number_of_network_namespaces + 1

    assert len(list_network_namespaces()) == number_of_network_namespaces

