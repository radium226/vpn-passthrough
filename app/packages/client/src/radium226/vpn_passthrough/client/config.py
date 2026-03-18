from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


DEFAULT_CONFIG_FOLDER_PATH = Path("/etc/vpn-passthrough")
_DEFAULT_SOCKET_FILE_PATH = Path("/run/vpn-passthrough/ipc.socket")


class ClientConfig(BaseModel):
    socket_file_path: Path = _DEFAULT_SOCKET_FILE_PATH

    @classmethod
    def load(cls, folder_path: Path | None = None) -> "ClientConfig":
        path = (folder_path or DEFAULT_CONFIG_FOLDER_PATH) / "client.yaml"
        data: dict[str, Any] = {}
        if path.exists():
            with path.open() as f:
                data = yaml.safe_load(f) or {}
        return cls.model_validate(data)


class TunnelConfig(BaseModel):
    name: str
    region_id: str | None = None
    names_of_ports_to_forward: list[str] = []
    backend_name: str | None = None
    veth_cidr: str | None = None
    rebind_ports_every: float | None = None
    ports_to_forward_from_vpeer_to_loopback: list[int] = []

    @classmethod
    def load_all(cls, folder_path: Path | None = None) -> dict[str, "TunnelConfig"]:
        tunnel_configs_folder_path = (folder_path or DEFAULT_CONFIG_FOLDER_PATH) / "tunnels"
        configs: dict[str, TunnelConfig] = {}
        if tunnel_configs_folder_path.is_dir():
            for path in sorted(tunnel_configs_folder_path.glob("*.yaml")):
                name = path.stem
                data: dict[str, Any] = {}
                with path.open() as f:
                    data = yaml.safe_load(f) or {}
                configs[name] = cls.model_validate({**data, "name": name})
        return configs
