from dataclasses import dataclass
from typing import NewType

User = NewType("User", str)
Password = NewType("Password", str)
Payload = NewType("Payload", str)
Signature = NewType("Signature", str)


@dataclass(frozen=True)
class Auth:
    user: User
    password: Password


@dataclass(frozen=True)
class PayloadAndSignature:
    payload: Payload
    signature: Signature


@dataclass(frozen=True)
class ForwardedPort:
    number: int
    payload_and_signature: PayloadAndSignature
