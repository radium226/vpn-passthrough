import functools
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import click

from radium226.vpn_passthrough.client import Client
from radium226.vpn_passthrough.messages import TunnelInfo


def pass_config_folder(f):
    @functools.wraps(f)
    def new_func(*args, **kwargs):
        ctx = click.get_current_context()
        return ctx.invoke(f, ctx.obj.config_folder_path, *args, **kwargs)
    return functools.update_wrapper(new_func, f)


@asynccontextmanager
async def lookup_or_create_tunnel(
    client: Client,
    tunnel_name: str | None,
    region_id: str | None,
    backend_name: str | None,
    kill_switch: bool = True,
) -> AsyncIterator[TunnelInfo]:
    """Yield a TunnelInfo, creating (and later destroying) a temporary tunnel when tunnel_name is None."""
    if tunnel_name is not None:
        yield await client.lookup_tunnel(tunnel_name)
        return

    temp_name = str(uuid.uuid4())
    tunnel_created = await client.create_tunnel(temp_name, region_id=region_id, backend_name=backend_name, kill_switch=kill_switch)
    try:
        yield tunnel_created.tunnel
    finally:
        await client.destroy_tunnel(temp_name)
