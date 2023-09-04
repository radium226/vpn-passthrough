from typing import NewType
from dataclasses import dataclass


User = NewType("User", str)


Password = NewType("Password", str)


RegionName = NewType("RegionName", str)


@dataclass
class Credentials():

    user: User

    password: Password