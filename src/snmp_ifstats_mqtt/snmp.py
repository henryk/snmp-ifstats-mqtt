import re
from hashlib import sha256
from itertools import chain
from typing import Iterable, Union

from easysnmp import Session

from .common import DataItem, DeviceData
from .mqtt import MQTTPublisher

IF_MIB_ROOT = "1.3.6.1.2.1.2.2.1"
ADSL_MIB_ROOT = "1.3.6.1.2.1.10.94"
HEX_BYTE_FIELDS = ("ifPhysAddress",)
INTEGER_FIELD_SUFFIXES = (
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
INTEGER_FIELDS = ("ifIndex", "ifMtu")
IGNORE_FIELDS = ("ifSpecific", "ifIndex", "ifType")
HIDE_IF_EMPTY = ("ifSpeed", "ifLastChange", "ifPhysAddress")


def camel_to_snake(name):
    name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def cast_value(name: str, value: str) -> Union[str, int]:
    if name in HEX_BYTE_FIELDS:
        value: str
        return bytearray(ord(x) for x in value).hex()
    elif (
        any(name.endswith(x) for x in INTEGER_FIELD_SUFFIXES) or name in INTEGER_FIELDS
    ):
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
        publisher: MQTTPublisher = None,
    ):
        self.session = Session(hostname=host, community=community, version=version)
        self.id_base = sha256(host.encode(errors="replace")).hexdigest()[:32]
        self.exclude = list(exclude)
        self.include = list(include)
        self.publisher = publisher

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

        id_names = {
            k: information_map[k].get("ifPhysAddress", None)
            or ("_" + information_map[k]["ifDescr"])
            for k in information_map.keys()
        }

        if self.publisher:
            for name, params in information_map.items():
                data_items = []

                for key, value in params.items():
                    if key in IGNORE_FIELDS:
                        continue

                    if key in HIDE_IF_EMPTY and (value == 0 or value in ("0", "")):
                        continue

                    uom = None
                    if key.endswith("Octets") or key.endswith("Mtu"):
                        uom = "bytes"
                    elif (
                        key.endswith("Atn")
                        or key.endswith("SnrMgn")
                        or key.endswith("Pwr")
                    ):
                        uom = "dBm"
                    elif key.endswith("Pkts"):
                        uom = "p"
                    elif key.endswith("Discards") or key.endswith("Errors"):
                        uom = "count"
                    elif key.startswith("adsl") and key.endswith("Rate"):
                        uom = "b/s"
                    elif key.endswith("Speed"):
                        uom = "b/s"

                    data_items.append(DataItem(camel_to_snake(key), value, uom))

                self.publisher.queue_device_data(
                    DeviceData(
                        name,
                        self.id_base + "-" + id_names[name],
                        True,
                        data_items,
                    )
                )
