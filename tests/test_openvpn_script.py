from threading import Thread
from vpn_passthrough.openvpn.script import ScriptServer, ScriptClient
from time import sleep
from pytest import mark

@mark.timeout(5)
def test_server_and_client():
    server = ScriptServer()
    
    def client_thread_target():
        sleep(2)
        client = ScriptClient()
        client.up(info={
            "route_vpn_gateway": "toto"
        })

    client_thread = Thread(target=client_thread_target)
    client_thread.start()
    

    server.start()
    up_info = server.wait_for_up()
    client_thread.join()
    assert up_info["route_vpn_gateway"] == "toto"
    print("We are here! ")

    server.stop()