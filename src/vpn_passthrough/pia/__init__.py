from typing import ClassVar, Any
from dataclasses import dataclass, field
from requests.auth import HTTPBasicAuth
from requests import Session
import requests
import json
from enum import StrEnum, auto
from ..network_namespace import NetworkNamespace
from ..commons import Credentials, RegionName
from subprocess import run
from pathlib import Path
from base64 import b64decode


class ServerType(StrEnum):

    META = "meta"
    OPENVPN_TCP = "ovpntcp"
    OPENVPN_UDP = "ovpnudp"
    WIREGUARD = "wg"
    INTERNET_KEY_EXCHANGE_V2 = "ikev2"



@dataclass
class Server():
    
    common_name: str
    ip_address: str


@dataclass
class Region():

    id: str
    name: str
    dns_host: str
    servers_by_type: dict[ServerType, list[Server]] = field(default_factory=dict)
    supports_port_forwarding: bool = False


@dataclass
class PayloadAndSignature():
    
    payload: str
    signature: str


@dataclass
class PIA():

    credentials: Credentials

    network_namespace: NetworkNamespace | None = None

    GENERATE_TOKEN_URL: ClassVar[str] = "https://privateinternetaccess.com/gtoken/generateToken"
    SERVERS_URL: ClassVar[str] = "https://serverlist.piaservers.net/vpninfo/servers/v6"

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass

    def generate_token(self) -> str:
        auth = HTTPBasicAuth(self.credentials.user, self.credentials.password)
        response = requests.get(PIA.GENERATE_TOKEN_URL, auth=auth)
        response.raise_for_status()
        json = response.json()
        token = json["token"]
        return token

    @classmethod
    def _parse_region(cls, obj: dict[str, Any]) -> Region:
        return Region(
            id=obj["id"],
            name=obj["name"],
            servers_by_type={ 
                ServerType(type_obj): [
                    cls._parse_server(server_obj)
                    for server_obj in server_objs
                ] 
                for type_obj, server_objs in obj["servers"].items()
            },
            supports_port_forwarding=obj["port_forward"],
            dns_host=obj["dns"]
        )

    @classmethod
    def _parse_server(csl, obj: dict[str, Any]) -> Server:
        return Server(
            common_name=obj["cn"],
            ip_address=obj["ip"],
        )

    @classmethod
    def list_regions(cls) -> list[Region]:
        response = requests.get(cls.SERVERS_URL, headers={"Accept": "application/json"})
        [text, *_] = response.text.splitlines()
        obj = json.loads(text)

        return [
            cls._parse_region(region_obj)
            for region_obj in obj["regions"]
        ]

    def generate_payload_and_signature(self, *, hostname: str, gateway: str) -> PayloadAndSignature:
        if self.network_namespace:
            token = self.generate_token()
            command = [
                "sudo",
                "ip", "netns", "exec", self.network_namespace.name,
                "curl", "-m", "5",
                "--connect-to", f"{hostname}::{gateway}:",
                "--cacert", str(Path(__file__).parent / "ca.rsa.4096.crt"),
                "-G", "--data-urlencode", f"token={token}",
                f"https://{hostname}:19999/getSignature",
            ]
            print(" ".join(command))

            # from time import sleep
            # sleep(60)

            stdout = run(command, capture_output=True, text=True, check=True).stdout
            obj = json.loads(stdout)
            payload = obj["payload"]
            signature = obj["signature"]
            return PayloadAndSignature(
                payload=payload,
                signature=signature,
            )
        else:
            raise Exception("Not yet implemented! ")

    def forward_port(self, *, hostname: str, gateway: str) -> int:
        payload_and_signature = self.generate_payload_and_signature(hostname=hostname, gateway=gateway)
        payload = payload_and_signature.payload
        signature = payload_and_signature.signature
        obj = json.loads(b64decode(payload).decode("utf-8"))
        port = int(obj["port"])
        self.bind_port(hostname=hostname, gateway=gateway, payload=payload, signature=signature)
        return port

    def bind_port(self, *, hostname: str, gateway: str, payload: str, signature: str):
        command = [
                "sudo",
                "ip", "netns", "exec", self.network_namespace.name,
                "curl", "-G", "-s", "-m", "5",
                "--connect-to", f"{hostname}::{gateway}:",
                "--cacert", str(Path(__file__).parent / "ca.rsa.4096.crt"),
                "--data-urlencode", f"payload={payload}",
                "--data-urlencode", f"signature={signature}",
                f"https://{hostname}:19999/bindPort",
            ]
        stdout = run(command, capture_output=True, text=True, check=True).stdout
        obj = json.loads(stdout)
        status = obj["status"]
        print(f"status={status}")

    @property
    def regions_by_name(self) -> dict[RegionName, Region]:
        return {
            region.name: region for region in self.list_regions()
        }
    
