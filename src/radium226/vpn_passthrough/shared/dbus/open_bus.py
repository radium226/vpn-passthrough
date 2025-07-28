from typing import (
    AsyncGenerator, 
    assert_never,
)
from contextlib import asynccontextmanager
from loguru import logger

from sdbus import (
    sd_bus_open_user,
    sd_bus_open_system,
    set_default_bus,
    SdBus,
)

from .bus_scope import BusScope



@asynccontextmanager
async def open_bus(scope: BusScope, is_default: bool = True) -> AsyncGenerator[SdBus, None]:
    logger.trace("open_dbus({scope})", scope=scope)
    match scope:
        case BusScope.SYSTEM:
            bus = sd_bus_open_system()
        
        case BusScope.SESSION:
            bus = sd_bus_open_user()

        case _:
            assert_never(scope)
    try:
        if is_default:
            set_default_bus(bus)
        yield bus
    finally:
        bus.close()