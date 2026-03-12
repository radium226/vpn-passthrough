from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


_SYSTEM_CONFIG_PATH = Path("/etc/vpn-passthrough/config.yaml")
_USER_CONFIG_PATH = Path("~/.config/vpn-passthrough/config.yaml").expanduser()
TUNNEL_CONFIGS_DIR = Path("/etc/vpn-passthrough/tunnels")
_DEFAULT_SOCKET_FILE_PATH = Path("/run/vpn-passthrough/ipc.socket")
_DEFAULT_NAMESPACE_FOLDER_PATH = Path("/run/vpn-passthrough/namespaces")


_ONE_WEEK = 7 * 24 * 3600.0


class Config(BaseModel):
    socket_file_path: Path = _DEFAULT_SOCKET_FILE_PATH
    namespace_base_folder_path: Path = _DEFAULT_NAMESPACE_FOLDER_PATH
    vpn_credentials: dict[str, str] | None = None
    vpn_backend: str | None = None
    region_id: str | None = None
    number_of_ports_to_forward: int = 0
    port_rebind_every: float = _ONE_WEEK

    def merge_with(self, other: "Config") -> "Config":
        base = self.model_dump()
        override = {k: v for k, v in other.model_dump().items() if k in other.model_fields_set}
        return Config.model_validate({**base, **override})

    @classmethod
    def load(cls, file_path: Path | None = None, *, skip_user_config: bool = False) -> "Config":
        config = cls._from_file(_SYSTEM_CONFIG_PATH)
        if not skip_user_config:
            config = config.merge_with(cls._from_file(_USER_CONFIG_PATH))
        if file_path is not None:
            config = config.merge_with(cls._from_file(file_path))
        return config

    @classmethod
    def _from_file(cls, path: Path) -> "Config":
        data: dict[str, Any] = {}
        if path.exists():
            with path.open() as f:
                data = yaml.safe_load(f) or {}
        return cls.model_validate(data)
