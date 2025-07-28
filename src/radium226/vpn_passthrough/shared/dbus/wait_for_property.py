from typing import Callable
from sdbus import DbusInterfaceCommonAsync
import asyncio
from loguru import logger

from sdbus.dbus_proxy_async_property import DbusBoundPropertyAsyncBase, DbusProxyPropertyAsync


class ToBe[V]():

    def __init__(self, expected_value: V):
        self.expected_value = expected_value

    def __call__(self, value: V) -> bool:
        return value == self.expected_value

    def __str__(self) -> str:
        return f"to be {self.expected_value}"

def to_be[V](expected_value: V) -> Callable[[V], bool]:
    return ToBe(expected_value)


async def wait_for_property[I: DbusInterfaceCommonAsync, V](
    property: DbusBoundPropertyAsyncBase[V],
    check: Callable[[V], bool],
) -> None:
    assert isinstance(property, DbusProxyPropertyAsync), "property must be an instance of DbusBoundPropertyAsyncBase"
    while True:
        try:
            value = await property.get_async()
            if check(value):
                logger.debug(f"Property {property.dbus_property.property_name} satisfied condition with value: {value}")
                return
            else:
                logger.debug(f"Property {property.dbus_property.property_name} changed to {value}, but does not satisfy condition {check}")
        except Exception as e:
            logger.error(f"Error while waiting for property {property.dbus_property.property_name}: {e}")
            raise e
        await asyncio.sleep(0.5)  # Adjust the sleep time as needed


    # wait_for_property_change_timeout = 0.33
    # while True:
    #     try:
    #         properties_changed = interface.properties_changed.catch()
    #         event = await asyncio.wait_for(anext(properties_changed), timeout=wait_for_property_change_timeout)
    #         logger.debug(f"Received properties changed event: {event}")
    #         # print(event)
    #         _, changed_properties, _ = event
    #         if property_name in changed_properties:
    #             dbus_type_signature, any_value = changed_properties[property_name]
    #             value = extract_property_value(dbus_type_signature, any_value)
    #             if check(value):
    #                 logger.debug(f"Property {property_name} satisfied condition with value: {value}")
    #                 return
    #             else:
    #                 logger.debug(f"Property {property_name} changed to {value}, but does not satisfy condition {check}")
    #     except asyncio.TimeoutError:
    #         logger.debug(f"Timeout waiting for property {property_name} to change, retrying...")
    #         properties = await interface.properties_get_all_dict()
    #         value = properties.get(property_name, None)
    #         if value:
    #             if check(value):
    #                 logger.debug(f"Property {property_name} satisfied condition with value: {value}")
    #                 return
    #     except Exception as e:
    #         logger.error(f"Error while waiting for property {property_name}: {e}")
    #         raise e
            
        

