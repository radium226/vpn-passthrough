import getpass

from ..teleporter import sudo

from .user import User

@sudo()
def get_user() -> User:
    return User(getpass.getuser())