FROM debian:bookworm-slim AS megatools-build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    meson \
    ninja-build \
    pkg-config \
    libglib2.0-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    ca-certificates \
    curl \
    patch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY patches/ /build/patches/
RUN curl --fail --show-error --location \
      https://deb.debian.org/debian/pool/main/m/megatools/megatools_1.11.5.orig.tar.gz \
      --output megatools.tar.gz \
    && echo "51f78a03748a64b1066ce28a2ca75d98dbef5f00fe9789dc894827f9a913b362  megatools.tar.gz" | sha256sum --check - \
    && tar -xzf megatools.tar.gz \
    && patch -d megatools-1.11.5.20250706 -p1 < patches/megatools-node-key-lookup.patch \
    && meson setup build megatools-1.11.5.20250706 --prefix=/usr/local -Dman=false \
    && meson compile -C build \
    && DESTDIR=/stage meson install -C build \
    && cp megatools.tar.gz /stage/usr/local/share/doc/megatools/source.tar.gz \
    && cp patches/megatools-node-key-lookup.patch /stage/usr/local/share/doc/megatools/

FROM python:3.12-slim-bookworm

LABEL maintainer="MegaSync"
LABEL description="Täglicher Mega-Downloader und Abgleich für Unraid Docker"

# Laufzeitbibliotheken für megatools; Compiler bleiben im Build-Stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libcurl4 \
    libssl3 \
    gosu \
    ca-certificates \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=megatools-build /stage/usr/local/ /usr/local/
RUN megatools dl --version | grep -F "megatools 1.11.5 -"

WORKDIR /app

# Standard-Verzeichnisse für Unraid
RUN mkdir -p /config /downloads /app

# Skripte kopieren
COPY sync.py /app/sync.py
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/sync.py /app/entrypoint.sh

# Standard Unraid Umgebungsvariablen
ENV PUID=99 \
    PGID=100 \
    UMASK=022 \
    TZ="Europe/Berlin" \
    LINKS_FILE="/config/Link.txt" \
    DOWNLOAD_DIR="/downloads" \
    SCAN_INTERVAL="86400" \
    SCAN_TIME="" \
    RUN_ON_STARTUP="true"

VOLUME ["/config", "/downloads"]

ENTRYPOINT ["/app/entrypoint.sh"]
