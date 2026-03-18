from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_FOLDER_PATH = Path("/etc/vpn-passthrough")
_DEFAULT_SOCKET_FILE_PATH = Path("/run/vpn-passthrough/ipc.socket")
_DEFAULT_NAMESPACE_FOLDER_PATH = Path("/run/vpn-passthrough/namespaces")
_DEFAULT_BACKENDS_FOLDER_PATH = Path("/etc/vpn-passthrough/backends")


@dataclass(frozen=True)
class ServerConfig:
    socket_file_path: Path = _DEFAULT_SOCKET_FILE_PATH
    namespace_base_folder_path: Path = _DEFAULT_NAMESPACE_FOLDER_PATH
    backends_folder_path: Path = _DEFAULT_BACKENDS_FOLDER_PATH
    default_backend_name: str | None = None

    @classmethod
    def load(cls, folder_path: Path | None = None) -> "ServerConfig":
        import yaml
        path = (folder_path or DEFAULT_CONFIG_FOLDER_PATH) / "server.yaml"
        data: dict[str, Any] = {}
        if path.exists():
            with path.open() as f:
                data = yaml.safe_load(f) or {}
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        for k, v in filtered.items():
            if k in ("socket_file_path", "namespace_base_folder_path", "backends_folder_path") and isinstance(v, str):
                filtered[k] = Path(v)
        return cls(**filtered)
