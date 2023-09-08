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
        # from time import sleep
        # sleep(5 * 60)

    assert len(list_network_namespaces()) == number_of_network_namespaces


def test_attach():
    

    with NetworkNamespace(name="test") as network_namespace:

        @network_namespace.attach
        def add(a, b):
            return a + b

        current_network_namespace_name = network_namespace.attach(lambda: NetworkNamespace.current().name)
        assert current_network_namespace_name() == "test"
        assert add(2, 3) == 5