ARG BUILD_FROM
FROM $BUILD_FROM as common-base

RUN apk add --no-cache \
    python3 net-snmp py3-pip
COPY ADSL-LINE-MIB /usr/share/snmp/mibs/
RUN mkdir /root/.snmp && echo mibs +ALL > /root/.snmp/snmp.conf
RUN python3 -m pip install -U pip && pip install -U setuptools wheel

FROM common-base as builder
RUN mkdir /install && \
    apk add --no-cache \
    alpine-sdk python3-dev net-snmp-dev \
    net-snmp-tools


COPY ./poetry.lock ./pyproject.toml ./
# FIXME Find a way to pre-cache dependencies
#RUN pip install --no-warn-script-location --prefix=/install --no-root  .

COPY . .
RUN pip install --no-warn-script-location --prefix=/install .

FROM common-base as runner
COPY --from=builder /install /usr
WORKDIR /data

CMD [ "snmp_ifstats_mqtt" ]
