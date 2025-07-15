from dataclasses import dataclass
import requests
import json



SERVERS_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"


def list_servers() -> None:
    response = requests.get(SERVERS_URL, headers={"Accept": "application/json"})
    response.raise_for_status()
    [text, *_] = response.text.splitlines()
    data = json.loads(text)

    for region in data["regions"]:
        print(region)
        print()