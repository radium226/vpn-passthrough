from vpn_passthrough.network_namespace import NetworkNamespace, list_network_namespaces
from vpn_passthrough.find_ip import find_ip

def test_network_namespace():
    number_of_network_namespaces = len(list_network_namespaces())
    ip_outside = find_ip()
    
    with NetworkNamespace(name="test") as network_namespace:
        assert len(list_network_namespaces()) == number_of_network_namespaces + 1
        network_namespace.exec(["ping", "-c", "1", "-W", "1", "www.google.fr"], check=True)
        ip_inside = find_ip(network_namespace=network_namespace)
        assert ip_inside == ip_outside

    assert len(list_network_namespaces()) == number_of_network_namespaces

