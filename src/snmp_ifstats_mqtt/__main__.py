import logging
import os
import time
from hashlib import sha256
from pathlib import Path

from dynaconf import Dynaconf

from snmp_ifstats_mqtt.mqtt import MQTTPublisher
from snmp_ifstats_mqtt.snmp import SNMPConnection


def main():
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))

    os.environ["MIBS"] = "+ALL"
    logging.info("ENV on start: %s", repr(dict(os.environ)))

    connections = []

    for connection in settings.connections:
        config = dict(
            {k: settings[k] for k in ("community", "version", "exclude", "include")},
            **connection,
        )
        connections.append(SNMPConnection(**config))

    mqttp = MQTTPublisher(
        id_hash=sha256(
            repr(sorted(connection.id_base for connection in connections)).encode()
        ).hexdigest()[:32],
        **settings.mqtt,
    )

    for connection in connections:
        connection.publisher = mqttp

    while True:
        for connection in connections:
            connection.poll()
        mqttp.publish()
        time.sleep(settings.INTERVAL)


settings = Dynaconf(
    envvar_prefix="SIM",
    settings_files=[
        "settings.toml",
        "settings.local.toml",
        ".secrets.toml",
        "/data/options.json",
    ],
    environments=False,
    load_dotenv=True,
    root_path=Path(__file__).parent,
    env_switcher="SIM_ENV",
)

if __name__ == "__main__":
    main()
