#!/bin/sh
set -e

PUID=${PUID:-99}
PGID=${PGID:-100}
UMASK=${UMASK:-022}

umask "$UMASK"

# Gruppe anpassen oder erstellen
if getent group megasync >/dev/null 2>&1; then
    groupmod -o -g "$PGID" megasync >/dev/null 2>&1 || true
else
    groupadd -o -g "$PGID" megasync >/dev/null 2>&1 || true
fi

# Benutzer anpassen oder erstellen
if getent passwd megasync >/dev/null 2>&1; then
    usermod -o -u "$PUID" -g "$PGID" -d /home/megasync megasync >/dev/null 2>&1 || true
else
    useradd -o -u "$PUID" -g "$PGID" -d /home/megasync -m -s /bin/sh megasync >/dev/null 2>&1 || true
fi

# Verzeichnisse anlegen falls nicht vorhanden
mkdir -p /config /downloads /home/megasync
chown -R "$PUID:$PGID" /home/megasync

# Berechtigungen prüfen & setzen (nur wenn root)
if [ "$(id -u)" = "0" ]; then
    chown "$PUID:$PGID" /downloads 2>/dev/null || true
    chown "$PUID:$PGID" /config 2>/dev/null || true
    
    # Falls Link.txt bereits existiert, Berechtigungen sicherstellen
    if [ -f "/config/Link.txt" ]; then
        chown "$PUID:$PGID" /config/Link.txt 2>/dev/null || true
    fi

    # Starte Skript als megasync Benutzer via gosu
    exec gosu "$PUID:$PGID" python3 /app/sync.py "$@"
else
    # Container läuft bereits als Nicht-Root
    exec python3 /app/sync.py "$@"
fi
