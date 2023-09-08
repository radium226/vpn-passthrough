from socket import socket, AF_INET, SOCK_STREAM
from threading import Thread, Event
from subprocess import run
from ..network_namespace import NetworkNamespace


def check_connectivity(
    local_port: int, 
    *, 
    local_address: str = "127.0.0.1", 
    remote_address: str | None = None, 
    remote_port: int | None = None,
    network_namespace: NetworkNamespace | None = None
) -> None:

    connectivity_event = Event()

    # def server_thread_target():
    #     try:
    #         with socket(AF_INET, SOCK_STREAM) as server_socket:
    #             server_socket.bind((local_address, local_port))
    #             server_socket.settimeout(10)
    #             server_socket.listen()
    #             print("[server] Waiting for something... ")
    #             connection, address = server_socket.accept()
    #             print("[server] Connected! ")
    #             payload = bytearray()
    #             with connection:
    #                 while True:
    #                     payload_part = connection.recv(1024)
    #                     payload.extend(payload_part)
    #                     if len(payload_part) < 1024:
    #                         break
    #                 ping = payload.decode("utf-8")
    #                 if ping != "ping":
    #                     raise Exception("Wrong payload (server)! ")
    #                 else:
    #                     connectivity_event.set()
    #                 connection.sendall(b"pong")
    #     except:
    #         pass

    def server_thread_target():
        ip_command_part = ["sudo", "ip", "netns", "exec", network_namespace.name] if network_namespace else []
        nc_command_part = ["nc", "-l", "-s", local_address, "-p", str(local_port), "-c", "-w", "10"]

        command = ip_command_part + nc_command_part
        
        output = run(command, text=True, input="pong", capture_output=True).stdout.strip()
        if not output:
            pass
        elif output != "ping":
            raise Exception("Wrong payload (server)! ")
        else:
            connectivity_event.set()


    server_thread = Thread(target=server_thread_target)
    server_thread.start()

    from time import sleep
    sleep(5)

    try:
        with socket(AF_INET, SOCK_STREAM) as client_socket:
            print("[client] Trying to connect... ")
            client_socket.connect((remote_address or local_address, remote_port or local_port))
            print("[client] Connected! ")
            client_socket.sendall(b"ping")
            payload = bytearray()
            while True:
                payload_part = client_socket.recv(1024)
                payload.extend(payload_part)
                if len(payload_part) < 1024:
                    break
            pong = payload.decode("utf-8")
            if pong != "pong":
                raise Exception("Wrong payload (client)! ")
    except:
        pass
        
    server_thread.join()

    if not connectivity_event.wait(timeout=10):
        raise Exception("Connectivity check failed")

                