from typing import Any, cast
from click import (
    command, 
    group, 
    argument,
    option,
    UNPROCESSED,
    ParamType,
    Parameter, 
    Context,
    pass_context,
)
from loguru import logger
import random
from dataclasses import dataclass

from .vpn_passthrough import open_vpn_passthrough, VPNPassthrough
from .pia import list_regions, Region, Credentials


@dataclass
class Config():

    pia_region: Region
    pia_credentials: Credentials
    name: str | None = None


class PIARegionType(ParamType):

    name = "pia-region"

    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Region:
        if not isinstance(value, str):
            self.fail(f"Invalid PIA region: {value}", param, ctx)
        
        pia_regions_by_id = { 
            region.id: region 
            for region in list_regions() 
        }
        return pia_regions_by_id[value]


class PIACredentialsType(ParamType):

    name = "pia-credentials"

    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> str:
        if not isinstance(value, str):
            self.fail(f"Invalid PIA credentials: {value}", param, ctx)
        
        # Here you would typically validate the credentials format
        [user, password] = value.split(":")
        return Credentials(
            user=user, 
            password=password,
        )


PIA_REGION_TYPE = PIARegionType()

PIA_CREDENTIALS_TYPE = PIACredentialsType()



@group()
@option("-n", "--name", "name", type=str, required=False)
@option(
    "-r", 
    "--pia-region", 
    "pia_region", 
    type=PIA_REGION_TYPE, 
    required=False,
    envvar="PIA_REGION",
)
@option(
    "-c", 
    "--pia-credentials", 
    "pia_credentials", 
    type=PIA_CREDENTIALS_TYPE, 
    required=True,
    envvar="PIA_CREDENTIALS",
)
@pass_context
def app(context: Context, name: str | None, pia_region: Region | None, pia_credentials: Credentials) -> None:
    context.obj = Config(
        name=name,
        pia_region=pia_region or random.choice(list_regions()),
        pia_credentials=pia_credentials,
    )


@app.command()
@argument("command", nargs=-1, type=UNPROCESSED)
@pass_context
def exec(
    context: Context,
    command: tuple[str, ...]
) -> None:
    assert len(command) > 0, "Command must not be empty"
    
    config = cast(Config, context.obj)
    
    pia_region = config.pia_region
    pia_credentials = config.pia_credentials
    name = config.name or command[0]

    logger.debug("config={config}", config=config)
    logger.debug("name={name}", name=name)
    logger.debug("pia_credentials={pia_credentials}", pia_credentials=pia_credentials)
    logger.debug("pia_region={pia_region}", pia_region=pia_region)

    with open_vpn_passthrough(name, pia_region=pia_region, pia_credentials=pia_credentials) as vpn_passthrough:
        vpn_passthrough.exec(list(command))

@app.command()
@pass_context
def show_ip(context: Context) -> None:
    config = cast(Config, context.obj)
    pia_region = config.pia_region
    pia_credentials = config.pia_credentials
    name = config.name or "show-ip"

    with open_vpn_passthrough(name, pia_region=pia_region, pia_credentials=pia_credentials) as vpn_passthrough:
        vpn_passthrough.exec(["curl", "-s", "https://api.ipify.org"])


@app.command()
@pass_context
def test_dns_leak(context: Context) -> None:
    config = cast(Config, context.obj)
    pia_region = config.pia_region
    pia_credentials = config.pia_credentials
    name = config.name or "dl"

    with open_vpn_passthrough(name, pia_region=pia_region, pia_credentials=pia_credentials) as vpn_passthrough:
        vpn_passthrough.exec(["dnsleaktest"])


@app.group()
def pia() -> None:
    """Commands for managing PIA VPN passthrough."""


@pia.command("list-regions")
def _list_regions() -> None:
    for region in list_regions():
        print(region)
        print("-----")


@pia.command("show-region")
@argument("pia-region", type=PIA_REGION_TYPE)
def show_region(pia_region: Region) -> None:
    print(pia_region)