from enum import (
    StrEnum,
    auto,
)
import os


class BusScope(StrEnum):

    SYSTEM = auto()
    SESSION = auto()


    @classmethod
    def auto(cls) -> "BusScope":
        if os.geteuid() == 0:
            return cls.SYSTEM
        else:
            return cls.SESSION