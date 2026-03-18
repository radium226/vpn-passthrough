from collections.abc import Callable
from contextlib import asynccontextmanager, AsyncExitStack
import os
from typing import AsyncIterator, Self

from radium226.vpn_passthrough.ipc import Server as IPCServer
from radium226.vpn_passthrough.ipc.protocol import RequestHandler
from radium226.vpn_passthrough.messages import BackendInfo, CODEC, CreateTunnel, DestroyTunnel, KillProcess, ListRegions, ListTunnels, RunProcess, StartTunnel, TunnelInfo

from .config import ServerConfig
from .service import BackendConfig, Service


class Server:
    def __init__(self, ipc_server: IPCServer, service: Service) -> None:
        self.ipc_server = ipc_server
        self.service = service

    @classmethod
    @asynccontextmanager
    async def listen(
        cls,
        config: ServerConfig,
        *,
        on_tunnels_changed: Callable[[list[TunnelInfo]], None] | None = None,
    ) -> AsyncIterator[Self]:
        cls._ensure_running_as_root()
        backends = [
            BackendInfo(
                name=backend_config.name,
                type=backend_config.type,
                credentials=backend_config.credentials,
            )
            for backend_config in BackendConfig.load_all(config.backends_folder_path)
        ]
        async with AsyncExitStack() as exit_stack:
            service = await exit_stack.enter_async_context(Service.create(
                namespace_base_folder_path=config.namespace_base_folder_path,
                backends=backends,
                default_backend_name=config.default_backend_name,
                on_tunnels_changed=on_tunnels_changed,
            ))
            ipc_server = await exit_stack.enter_async_context(IPCServer.listen(
                config.socket_file_path,
                [
                    RequestHandler(request_type=RunProcess, on_request=service.handle_run_process),
                    RequestHandler(request_type=KillProcess, on_request=service.handle_kill_process),
                    RequestHandler(request_type=CreateTunnel, on_request=service.handle_create_tunnel),
                    RequestHandler(request_type=StartTunnel, on_request=service.handle_start_tunnel),
                    RequestHandler(request_type=DestroyTunnel, on_request=service.handle_destroy_tunnel),
                    RequestHandler(request_type=ListRegions, on_request=service.handle_list_regions),
                    RequestHandler(request_type=ListTunnels, on_request=service.handle_list_tunnels),
                ],
                CODEC,
            ))
            yield cls(ipc_server, service)

    async def wait_forever(self) -> None:
        await self.ipc_server.wait_forever()

    @classmethod
    def _ensure_running_as_root(cls) -> None:
        if os.geteuid() != 0:
            raise PermissionError("This server must be run as root to manage network namespaces and processes.")
