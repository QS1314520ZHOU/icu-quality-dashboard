FROM oraclelinux:8.2 AS builder

ENV PYTHON_VERSION=3.11.9 \
    NODE_MAJOR=20 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN dnf -y install oracle-epel-release-el8 && \
    dnf -y groupinstall "Development Tools" && \
    dnf -y install openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel wget tar gzip make findutils && \
    dnf clean all

RUN wget -q https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz && \
    tar -xzf Python-${PYTHON_VERSION}.tgz && \
    cd Python-${PYTHON_VERSION} && \
    ./configure --enable-optimizations --prefix=/opt/python-${PYTHON_VERSION} && \
    make -j"$(nproc)" && \
    make install && \
    ln -s /opt/python-${PYTHON_VERSION}/bin/python3 /usr/local/bin/python3 && \
    ln -s /opt/python-${PYTHON_VERSION}/bin/pip3 /usr/local/bin/pip3

RUN dnf -y module reset nodejs && \
    dnf -y module enable nodejs:${NODE_MAJOR} && \
    dnf -y install nodejs && \
    dnf clean all

COPY icu-quality-backend/requirements.txt /build/requirements.txt
RUN pip3 install --upgrade pip setuptools wheel && \
    pip3 install -r /build/requirements.txt pyinstaller

COPY icu-quality-dashboard/package*.json /build/frontend/
WORKDIR /build/frontend
RUN npm ci

COPY icu-quality-dashboard /build/frontend
RUN npm run build

COPY icu-quality-backend /build/backend
RUN mkdir -p /build/backend/frontend_dist && \
    cp -a /build/frontend/dist/. /build/backend/frontend_dist/

WORKDIR /build/backend
RUN pyinstaller \
    --clean \
    --name icu-quality-dashboard \
    --onefile \
    --add-data "frontend_dist:frontend_dist" \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto \
    main.py

FROM oraclelinux:8.2 AS artifact

WORKDIR /artifact/icu-quality-dashboard
COPY --from=builder /build/backend/dist/icu-quality-dashboard ./icu-quality-dashboard
COPY deploy/env.template ./.env.template
COPY deploy/README.md ./README.md

RUN chmod +x ./icu-quality-dashboard && \
    cd /artifact && \
    tar -czf icu-quality-dashboard-oel8.2-x86_64.tar.gz icu-quality-dashboard
