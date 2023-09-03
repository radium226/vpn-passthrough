from typing import ClassVar
from dataclasses import dataclass
from requests.auth import HTTPBasicAuth
from requests import Session
import requests

@dataclass
class PIA():

    user: str
    password: str

    GENERATE_TOKEN_URL = "https://privateinternetaccess.com/gtoken/generateToken'"

    def generate_token(self) -> str:
        auth = HTTPBasicAuth(self.user, self.password)
        response = requests.get(PIA.GENERATE_TOKEN_URL, auth=auth)
        response.raise_for_status()
        json = response.json()
        token = json["token"]
        return token

    
