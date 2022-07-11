import logging
import time
from itertools import chain
from pathlib import Path
from typing import Iterable

from dynaconf import Dynaconf
from easysnmp import Session

IF_MIB_ROOT = "1.3.6.1.2.1.2.2.1"
ADSL_MIB_ROOT = "1.3.6.1.2.1.10.94"


def cast_value(name, value):
    if name in ("ifPhysAddress",):
        value: str
        return bytearray(ord(x) for x in value).hex()
    elif any(
        name.endswith(x)
        for x in (
            "Length",
            "Rate",
            "Delay",
            "Discards",
            "Errors",
            "Pkts",
            "QLen",
            "Speed",
            "Octets",
            "Atn",
            "SnrMgn",
            "UnknownProtos",
        )
    ):
        return int(value)
    elif name in ("ifIndex", "ifMtu"):
        return int(value)
    return value.rstrip("\x00")


class SNMPConnection:
    def __init__(
        self,
        host: str,
        version: int,
        community: str,
        exclude: Iterable[str] = (),
        include: Iterable[str] = (),
    ):
        self.session = Session(hostname=host, community=community, version=version)
        self.exclude = list(exclude)
        self.include = list(include)

    def poll(self):
        information = {}

        for value in chain(
            self.session.walk(IF_MIB_ROOT), self.session.walk(ADSL_MIB_ROOT)
        ):
            inf = information.setdefault(value.oid_index, dict())
            inf[value.oid] = value

        for k in list(information.keys()):
            if (
                "ifDescr" not in information[k]
                or information[k]["ifDescr"].snmp_type != "OCTETSTR"
                or not information[k]["ifDescr"].value
                or not (
                    (
                        not self.include
                        or information[k]["ifDescr"].value in self.include
                    )
                    and (information[k]["ifDescr"].value not in self.exclude)
                )
            ):
                del information[k]

        information_map = {
            inf["ifDescr"].value: {k: cast_value(k, v.value) for (k, v) in inf.items()}
            for inf in information.values()
        }

        import pprint

        pprint.pprint(information_map)


def main():
    logging.basicConfig(level=logging.INFO)

    connections = []

    for connection in settings.connections:
        config = dict(
            {k: settings[k] for k in ("community", "version", "exclude", "include")},
            **connection,
        )
        connections.append(SNMPConnection(**config))

    while True:
        for connection in connections:
            print(connection.session)
            connection.poll()
        time.sleep(1)


settings = Dynaconf(
    envvar_prefix="SIM",
    settings_files=["settings.toml", "settings.local.toml", ".secrets.toml"],
    environments=False,
    load_dotenv=True,
    root_path=Path(__file__).parent,
    env_switcher="SIM_ENV",
)

if __name__ == "__main__":
    main()
