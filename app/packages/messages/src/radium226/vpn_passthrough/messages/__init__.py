from typing import Annotated, Literal, Never

from pydantic import BaseModel, Discriminator, TypeAdapter

from radium226.vpn_passthrough.ipc.protocol import Codec, Request


type TunnelName = str

type RequestID = str


class ProcessTerminated(BaseModel):
    request_id: RequestID
    exit_code: int
    type: Literal["process_terminated"] = "process_terminated"


class CommandNotFound(BaseModel):
    request_id: str
    command: str
    type: Literal["command_not_found"] = "command_not_found"


class ProcessStarted(BaseModel):
    pid: int
    type: Literal["process_started"] = "process_started"


class ProcessRestarted(BaseModel):
    pid: int
    forwarded_ports: dict[str, int] = {}
    type: Literal["process_restarted"] = "process_restarted"


class RunProcess(BaseModel, Request[ProcessTerminated | CommandNotFound, ProcessStarted | ProcessRestarted]):
    id: str
    command: str
    args: list[str] = []
    kill_with: int | None = None
    tunnel_name: str | None = None
    cwd: str | None = None
    username: str | None = None
    gid: int | None = None
    ambient_capabilities: list[int] = []
    client_pid: int | None = None
    env: dict[str, str] = {}
    configure_with: str | None = None
    type: Literal["run_process"] = "run_process"


class ProcessKilled(BaseModel):
    request_id: str
    pid: int
    type: Literal["process_killed"] = "process_killed"


class KillProcess(BaseModel, Request[ProcessKilled, Never]):
    id: str
    pid: int
    signal: int
    type: Literal["kill_process"] = "kill_process"


class ProcessInfo(BaseModel):
    pid: int
    command: str
    args: list[str] = []


class BackendInfo(BaseModel):
    name: str
    type: str
    credentials: dict[str, str] = {}


class TunnelInfo(BaseModel):
    name: str
    vpn_connected: bool = False
    region_id: str | None = None
    public_ip: str | None = None
    gateway_ip: str | None = None
    tun_ip: str | None = None
    forwarded_ports: dict[str, int] = {}
    veth: str | None = None
    veth_addr: str | None = None
    vpeer: str | None = None
    vpeer_addr: str | None = None
    processes: list[ProcessInfo] = []


class TunnelCreated(BaseModel):
    request_id: str
    name: str
    tunnel: TunnelInfo
    type: Literal["tunnel_created"] = "tunnel_created"


class TunnelDestroyed(BaseModel):
    request_id: str
    name: str
    type: Literal["tunnel_destroyed"] = "tunnel_destroyed"


class ConnectedToVPN(BaseModel):
    remote_ip: str
    gateway_ip: str
    tun_ip: str
    forwarded_ports: dict[str, int]
    type: Literal["connected_to_vpn"] = "connected_to_vpn"


class DNSConfigured(BaseModel):
    nameservers: list[str]
    type: Literal["dns_configured"] = "dns_configured"


class CreateTunnel(BaseModel, Request[TunnelCreated, ConnectedToVPN | DNSConfigured]):
    id: str
    name: str
    region_id: str | None = None
    names_of_ports_to_forward: list[str] = []
    backend_name: str | None = None
    veth_cidr: str | None = None
    type: Literal["create_tunnel"] = "create_tunnel"


class ConfigUsed(BaseModel):
    region_id: str | None
    backend_name: str | None
    names_of_ports_to_forward: list[str]
    type: Literal["config_used"] = "config_used"


class TunnelStarted(BaseModel):
    name: str
    type: Literal["tunnel_started"] = "tunnel_started"


class TunnelStatusUpdated(BaseModel):
    info: TunnelInfo
    type: Literal["tunnel_status_updated"] = "tunnel_status_updated"


class PortsRebound(BaseModel):
    forwarded_ports: dict[str, int]
    type: Literal["ports_rebound"] = "ports_rebound"


class TunnelStopped(BaseModel):
    request_id: str
    name: str
    type: Literal["tunnel_stopped"] = "tunnel_stopped"


class StartTunnel(BaseModel, Request["TunnelStopped", "ConfigUsed | TunnelStarted | ConnectedToVPN | DNSConfigured | TunnelStatusUpdated | PortsRebound"]):
    id: str
    name: str
    region_id: str | None = None
    names_of_ports_to_forward: list[str] = []
    backend_name: str | None = None
    rebind_ports_every: float | None = None
    veth_cidr: str | None = None
    type: Literal["start_tunnel"] = "start_tunnel"


class DestroyTunnel(BaseModel, Request[TunnelDestroyed, Never]):
    id: str
    name: str
    type: Literal["destroy_tunnel"] = "destroy_tunnel"


class Country(BaseModel):
    region_id: str
    name: str
    country: str
    port_forward: bool = False


class RegionsListed(BaseModel):
    request_id: str
    countries: list[Country]
    type: Literal["regions_listed"] = "regions_listed"


class ListRegions(BaseModel, Request[RegionsListed, Never]):
    id: str
    backend_name: str | None = None
    type: Literal["list_regions"] = "list_regions"


class TunnelsListed(BaseModel):
    request_id: str
    tunnels: list[TunnelInfo]
    type: Literal["tunnels_listed"] = "tunnels_listed"


class ListTunnels(BaseModel, Request[TunnelsListed, Never]):
    id: str
    type: Literal["list_tunnels"] = "list_tunnels"


type _Response = Annotated[ProcessTerminated | CommandNotFound | ProcessKilled | TunnelCreated | TunnelDestroyed | TunnelStopped | RegionsListed | TunnelsListed, Discriminator("type")]
type _Event = ProcessStarted | ProcessRestarted | ConnectedToVPN | DNSConfigured | ConfigUsed | TunnelStarted | TunnelStatusUpdated | PortsRebound

_TYPE_ADAPTER = TypeAdapter(
    Annotated[
        RunProcess | KillProcess | CreateTunnel | StartTunnel | DestroyTunnel | ListRegions | ListTunnels | ProcessStarted | ProcessRestarted | ConnectedToVPN | DNSConfigured | ConfigUsed | TunnelStarted | TunnelStatusUpdated | PortsRebound | ProcessTerminated | CommandNotFound | ProcessKilled | TunnelCreated | TunnelDestroyed | TunnelStopped | RegionsListed | TunnelsListed,
        Discriminator("type"),
    ]
)


def _encode(message: RunProcess | KillProcess | CreateTunnel | StartTunnel | DestroyTunnel | ListRegions | ListTunnels | _Event | _Response) -> bytes:
    return message.model_dump_json().encode()


def _decode(data: bytes) -> RunProcess | KillProcess | CreateTunnel | StartTunnel | DestroyTunnel | ListRegions | ListTunnels | _Event | _Response:
    return _TYPE_ADAPTER.validate_json(data.decode())


CODEC = Codec[RunProcess | KillProcess | CreateTunnel | StartTunnel | DestroyTunnel | ListRegions | ListTunnels, ProcessStarted | ProcessRestarted | ConnectedToVPN | DNSConfigured | ConfigUsed | TunnelStarted | TunnelStatusUpdated | PortsRebound, ProcessTerminated | CommandNotFound | ProcessKilled | TunnelCreated | TunnelDestroyed | TunnelStopped | RegionsListed | TunnelsListed](
    encode=_encode,
    decode=_decode,
)
