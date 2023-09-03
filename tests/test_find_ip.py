from vpn_passthrough.find_ip import find_ip


def test_find_ip():
    ip = find_ip()
    print(ip)