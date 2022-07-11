import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import chain
from pathlib import Path
from typing import Iterable, List, Optional, Union

from dynaconf import Dynaconf
from easysnmp import Session
from paho.mqtt.client import Client

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


@dataclass
class DataItem:
    name: str
    value: Union[str, int]
    unit_of_measurement: Optional[str] = None


@dataclass
class DeviceData:
    name: str
    unique_name: str
    present: bool = False
    items: List[DataItem] = field(default_factory=list)


class MQTTPublisher:
    def __init__(self, broker, username, password, discovery_prefix="homeassistant"):
        self.broker = broker
        self.username = username
        self.password = password
        self.discovery_prefix = discovery_prefix
        self.queue: List[DeviceData] = []
        self.temp_id = str(uuid.uuid4())

        self.mqtt_client = Client()
        self.mqtt_client.will_set(self.availability_topic, "offline", retain=False)
        if self.username and self.password:
            self.mqtt_client.username_pw_set(
                username=self.username, password=self.password
            )
        self.mqtt_client.connect(host=self.broker, keepalive=25)
        self.mqtt_client.publish(self.availability_topic, "online", retain=True)

        self.discovery_data = {}

    @property
    def availability_topic(self):
        return self.discovery_prefix + "/_meta/" + self.temp_id

    def queue_device_data(self, data: DeviceData):
        self.queue.append(data)

    def publish(self):
        for ddata in self.queue:
            device_data = {
                "name": ddata.name,
                "identifiers": ddata.unique_name,
            }

            for edata in ddata.items:
                basename = "/".join(
                    [
                        self.discovery_prefix,
                        "sensor",
                        ddata.unique_name + "-" + edata.name,
                    ]
                )
                discovery_data = {
                    "~": basename,
                    "device": device_data,
                    "name": ddata.name + " " + edata.name,
                    "unique_id": ddata.unique_name + "-" + edata.name,
                    "availability": [
                        {
                            "topic": self.availability_topic,
                            "payload_available": "online",
                            "payload_not_available": "offline",
                        }
                    ],
                    "state_topic": "~/state",
                }
                if edata.unit_of_measurement:
                    discovery_data["unit_of_measurement"] = edata.unit_of_measurement

                if (
                    basename not in self.discovery_data
                    or self.discovery_data[basename] != discovery_data
                ):
                    self.mqtt_client.publish(
                        basename + "/config", json.dumps(discovery_data), retain=True
                    )
                    self.discovery_data[basename] = discovery_data

                # print(edata.name, edata.value)
                self.mqtt_client.publish(basename + "/state", str(edata.value))

        del self.queue[:]


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
                        uom = "packets"
                    elif key.endswith("Discards") or key.endswith("Errors"):
                        uom = "count"
                    elif key.startswith("adsl") and key.endswith("Rate"):
                        uom = "bits/s"
                    data_items.append(DataItem(camel_to_snake(key), value, uom))

                self.publisher.queue_device_data(
                    DeviceData(
                        name,
                        self.id_base + "-" + id_names[name],
                        True,
                        data_items,
                    )
                )


def main():
    logging.basicConfig(level=logging.INFO)

    mqttp = MQTTPublisher(**settings.mqtt)

    connections = []

    for connection in settings.connections:
        config = dict(
            {k: settings[k] for k in ("community", "version", "exclude", "include")},
            **connection,
        )
        connections.append(SNMPConnection(publisher=mqttp, **config))

    while True:
        for connection in connections:
            connection.poll()
        mqttp.publish()
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
