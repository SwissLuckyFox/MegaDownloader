FROM python:3.12-slim-bookworm

LABEL maintainer="MegaSync"
LABEL description="Täglicher Mega-Downloader und Abgleich für Unraid Docker"

# Systempakete installieren: megatools, gosu (für Unraid PUID/PGID), ca-certificates, tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
    megatools \
    gosu \
    ca-certificates \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

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
