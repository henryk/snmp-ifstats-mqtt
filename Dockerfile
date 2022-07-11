ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    python3 curl net-snmp alpine-sdk python3-dev net-snmp-dev \
    net-snmp-tools

COPY ADSL-LINE-MIB /usr/share/snmp/mibs/
RUN mkdir /root/.snmp && echo mibs +ALL > /root/.snmp/snmp.conf

ARG POETRY_VERSION=1.1.13
ENV POETRY_VERSION=$POETRY_VERSION
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH "/root/.local/bin:$PATH"

COPY ./poetry.lock ./pyproject.toml ./
RUN poetry install --no-dev --no-root

COPY . .
RUN poetry install --no-dev

WORKDIR /data

CMD [ "poetry", "run", "snmp_ifstats_mqtt" ]
