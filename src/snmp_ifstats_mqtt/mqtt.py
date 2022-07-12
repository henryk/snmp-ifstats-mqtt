import json
import logging
import uuid
from typing import List, Optional

from paho.mqtt.client import Client

from .common import DeviceData

logger = logging.getLogger(__name__)


class MQTTPublisher:
    def __init__(
        self,
        broker,
        username,
        password,
        discovery_prefix="homeassistant",
        id_hash: Optional[str] = None,
    ):
        self.broker = broker
        self.username = username
        self.password = password
        self.discovery_prefix = discovery_prefix
        self.queue: List[DeviceData] = []
        self.temp_id = id_hash if id_hash else str(uuid.uuid4())

        self.mqtt_client = Client()
        self.mqtt_client.will_set(self.availability_topic, "offline", retain=True)
        if self.username and self.password:
            self.mqtt_client.username_pw_set(
                username=self.username, password=self.password
            )
        self.mqtt_client.connect(host=self.broker, keepalive=25)
        self.mqtt_client.publish(self.availability_topic, "online", retain=True)

        self.discovery_data = {}

    @property
    def availability_topic(self):
        return self.discovery_prefix + "/_meta/" + self.temp_id + "/status"

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
                        "snmp_ifstats",
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
                    logger.info("Discovered %s of device %s", edata, ddata.name)

                # print(edata.name, edata.value)
                self.mqtt_client.publish(basename + "/state", str(edata.value))

        del self.queue[:]
