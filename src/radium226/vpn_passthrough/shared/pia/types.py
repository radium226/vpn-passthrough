from dataclasses import dataclass
from typing import Optional



@dataclass
class Server:
    ip: str
    cn: str
    van: Optional[bool] = None


@dataclass
class Servers:
    ikev2: list[Server]
    meta: list[Server]
    ovpntcp: list[Server]
    ovpnudp: list[Server]
    wg: list[Server]


type RegionID = str

@dataclass
class Region:
    id: RegionID
    name: str
    country: str
    auto_region: bool
    dns: str
    port_forward: bool
    geo: bool
    offline: bool
    servers: Servers


@dataclass
class Credentials():
    user: str
    password: str


type Payload = str

type Signature = str

@dataclass
class PayloadAndSignature:
    payload: Payload
    signature: Signature