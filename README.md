# MegaSync für Unraid (Docker)

Ein automatisierter, schlanker Docker-Container für Unraid, der konfigurierte **MEGA-Links täglich prüft**, bestehende Dateien abgleicht und **nur neue oder veränderte Dateien herunterlädt**.

---

## Highlights

* 🔄 **Täglicher automatischer Abgleich:** Prüft entweder zu einer festen Uhrzeit (z. B. jeden Tag um `03:00` Uhr) oder in einem frei wählbaren Intervall (z. B. alle 24 Stunden).
* 📝 **Dynamische `Link.txt`:** Die Links liegen in einer Textdatei auf deinem Unraid-Server. Bei **jedem Prüflauf** wird die Datei frisch eingelesen – du kannst Links jederzeit hinzufügen, ändern oder entfernen, **ohne** den Container neu starten zu müssen.
* 📍 **Frei bestimmbarer Speicherort:** Der Ort der `Link.txt` kann auf Unraid beliebig gewählt werden (z. B. `/mnt/user/appdata/megasync/Link.txt`).
* 📁 **Intelligenter Download:** Verwendet `megatools dl`, vergleicht Dateigrößen und überspringt bereits vorhandene Dateien automatisch.
* 🛡️ **Unraid-optimiert:** Unterstützt `PUID=99` und `PGID=100` (`nobody:users`), sodass heruntergeladene Dateien problemlos über Windows-/SMB-Freigaben geöffnet und bearbeitet werden können.
* ⏸️ **Unterbrechungsfrei:** Reagiert sauber auf Neustart- und Stopp-Signale von Unraid.

---

## Projektstruktur

```
Megasync/
├── Dockerfile                      # Docker-Image Definition (Debian + megatools + Python)
├── sync.py                         # Synchronisations- und Scheduling-Dienst
├── entrypoint.sh                   # Berechtigungs- & PUID/PGID-Manager
├── .github/workflows/docker-publish.yml # Automatischer Build und GHCR-Push
├── Link.example.txt                # Öffentliche Vorlage ohne echte Links
├── Link.txt                        # Private Konfiguration, von Git ignoriert
├── docker-compose.yml              # Für Docker Compose / Portainer
├── megasync-unraid-template.xml    # Vorlage für das Unraid WebUI
└── README.md                       # Anleitung
```

---

## Format der `Link.txt`

Erstelle oder bearbeite die Datei `Link.txt` auf deinem Unraid-Server:

```text
# ============================================================
# MegaSync - Link Konfiguration
# ============================================================
# Trage hier deine MEGA-Links ein (ein Link pro Zeile).
# Zeilen mit '#' und Leerzeilen werden ignoriert.

https://mega.nz/folder/ABC123xyz#SCHLUESSEL1
https://mega.nz/folder/DEF456uvw#SCHLUESSEL2
https://mega.nz/folder/GHI789rst#SCHLUESSEL3

# Optional: Mit einem '|' kannst du einen Ziel-Unterordner festlegen:
# https://mega.nz/folder/JKL012mno#SCHLUESSEL4 | Serien
```

---

## Installation auf Unraid

### Methode 1: GitHub + fertiges Image (empfohlen)

Repository: `https://github.com/SwissLuckyFox/MegaDownloader`

Image: `ghcr.io/swissluckyfox/megadownloader:latest`

#### Einmalig auf GitHub einrichten

1. Erstelle auf GitHub das Repository **MegaDownloader** unter **SwissLuckyFox**.
   Verwende den Standardbranch `main` (auch `master` wird unterstützt).
2. Lade die Projektdateien einschließlich `.github/workflows/docker-publish.yml`,
   `.gitignore` und `.dockerignore` hoch. **Link.txt und Zugangsdaten nicht hochladen!**
   Die lokale `Link.txt` wird von Git ignoriert; beim manuellen Upload im Browser
   musst du sie selbst ausschließen. Nutze `Link.example.txt` als öffentliche Vorlage.
3. Unter **Actions** läuft nach jedem Push auf den Standardbranch der Workflow
   **Build and publish Docker image**. Er lässt sich auch manuell starten.
   Er baut ein `linux/amd64`-Image für übliche Intel-/AMD-Unraid-Systeme,
   prüft Syntax und Containerstart und veröffentlicht erst danach das Image.
4. Für die Veröffentlichung wird das automatisch bereitgestellte `GITHUB_TOKEN`
   verwendet. Ein eigenes Registry-Passwort ist nicht erforderlich.
5. Nach dem ersten erfolgreichen Build: Öffne auf deinem GitHub-Profil
   **Packages → megadownloader → Package settings → Change visibility → Public**.
   Das Paket kann anfangs privat sein, auch bei einem öffentlichen Repository.
   Erst als öffentliches Paket kann Unraid es ohne Registry-Anmeldung laden.
   Falls eine Organisationsrichtlinie den Push blockiert, muss dort der
   Schreibzugriff auf Packages für GitHub Actions freigegeben werden.

Das Image erhält die Tags `latest` und `sha-<vollständige Commit-ID>`.
Änderungen am Code erzeugen ein neues Image; Änderungen an deiner privaten
Link-Datei benötigen weder GitHub noch einen neuen Build.

#### Auf Unraid installieren

Verwende das unten beschriebene Unraid-Template oder die Compose-Datei.
Ein lokaler Image-Build ist nicht nötig. In der Unraid-WebUI muss im Feld
**Repository** stehen:

```text
ghcr.io/swissluckyfox/megadownloader:latest
```

Wähle beim Pfad **Config-Verzeichnis (Link.txt)** den gewünschten Host-Ordner,
zum Beispiel `/mnt/user/appdata/megasync`. Er wird nach `/config` eingebunden;
die private Datei liegt dann auf Unraid in diesem Ordner und heißt `Link.txt`.
**Den Ordner einbinden, nicht nur die Datei:** So werden auch Änderungen durch
Editoren erkannt, die beim Speichern die Datei ersetzen.

Der Container erstellt bei Bedarf eine kommentierte Vorlage. Trage dort deine
drei Links ein. Die Datei wird bei jedem Prüflauf neu gelesen.

Für Compose lässt sich der Host-Ordner auch über eine lokale `.env` festlegen:

```text
LINKS_DIR=/mnt/user/meine-konfiguration/megasync
```

Bei Image-Updates in Unraid **Nach Updates suchen → Aktualisieren** verwenden.
Compose aktualisiert das Image mit `docker compose pull` und
`docker compose up -d`. GitHub aktualisiert den laufenden Unraid-Container
nicht automatisch. Die eingebundenen Konfigurations- und Download-Ordner bleiben
erhalten.

### Alternative: Image lokal auf Unraid bauen

1. Kopiere den Ordner `Megasync` auf dein Unraid-System (z. B. nach `/mnt/user/appdata/megasync-build` oder in dein Home-Verzeichnis).
2. Öffne das Unraid-Terminal und baue das Image einmalig:
   ```bash
   cd /mnt/user/appdata/megasync-build
   docker build -t megasync:latest .
   ```

3. Starte den Container per `docker run`:
   ```bash
   docker run -d \
     --name=megasync \
     --restart=unless-stopped \
     -e PUID=99 \
     -e PGID=100 \
     -e UMASK=022 \
     -e TZ="Europe/Berlin" \
     -e SCAN_TIME="03:00" \
     -e RUN_ON_STARTUP="true" \
     -v /mnt/user/appdata/megasync:/config \
     -v /mnt/user/downloads/megasync:/downloads \
     megasync:latest
   ```

> **Tipp:** Wenn du den Ordner `/mnt/user/appdata/megasync` nach `/config` mappst, wird die Datei `/mnt/user/appdata/megasync/Link.txt` automatisch verwendet. Falls sie noch nicht existiert, legt der Container beim ersten Start automatisch eine Vorlage an!

---

### Methode 2: Unraid Docker-WebUI (Template)

1. Warte auf den erfolgreichen GitHub-Actions-Build und stelle das GHCR-Paket auf öffentlich.
2. Kopiere die Datei `megasync-unraid-template.xml` in das Unraid-Vorlagenverzeichnis auf dem Flash-Laufwerk:
   `/boot/config/plugins/dockerMan/templates-user/my-megasync.xml`
3. Gehe im Unraid WebUI auf den Reiter **Docker** -> **Container hinzufügen**.
4. Wähle oben unter **Vorlage** `megasync` aus.
5. Alle Pfade und Variablen sind bereits vorkonfiguriert:
   * **Config-Verzeichnis:** `/mnt/user/appdata/megasync` (hier liegt `Link.txt`)
   * **Download-Verzeichnis:** `/mnt/user/downloads/megasync` (hier landen die Downloads)
   * **Tägliche Prüfzeit:** z. B. `03:00`
6. Klicke auf **Anwenden**.

---

### Methode 3: Mit Docker Compose (Unraid Plugin "Docker Compose Manager")

Nutze einfach die beiliegende `docker-compose.yml`:

```bash
docker compose up -d
```

---

## Umgebungsvariablen (Optionen)

| Variable | Standardwert | Beschreibung |
|---|---|---|
| `LINKS_FILE` | `/config/Link.txt` | Pfad zur `Link.txt` innerhalb des Containers. |
| `DOWNLOAD_DIR` | `/downloads` | Zielordner für die Downloads. |
| `SCAN_TIME` | `03:00` | Feste tägliche Uhrzeit (`HH:MM`) für den Abgleich (z. B. `03:00` Uhr nachts). |
| `SCAN_INTERVAL` | `86400` | Intervall in Sekunden (oder z. B. `24h`, `1d`), falls `SCAN_TIME` leer gelassen wird. |
| `RUN_ON_STARTUP`| `true` | Führt direkt nach dem Containerstart einen ersten Suchlauf durch. |
| `PUID` | `99` | Unraid User-ID (`nobody`), verhindert Dateiberechtigungsprobleme. |
| `PGID` | `100` | Unraid Group-ID (`users`). |
| `UMASK` | `022` | Standard-Dateiberechtigungsmaske. |
| `TZ` | `Europe/Berlin` | Zeitzone für korrekte Uhrzeiten in den Logs. |
| `MEGA_USERNAME` | *(leer)* | Optional: E-Mail für deinen MEGA-Account (höheres Kontingent). |
| `MEGA_PASSWORD` | *(leer)* | Optional: Passwort deines MEGA-Accounts. |
| `SPEED_LIMIT`   | *(leer)* | Optional: Bandbreitenbegrenzung für Downloads (z. B. `10M` für 10 MB/s). |

---

## Funktionsweise & Logs

### Download-Fortschritt

Die Fortschrittsausgabe von `megatools` ist aktiviert. Prozentmeldungen pro Datei
werden als `[Fortschritt]` geloggt: bei der ersten Meldung einer Datei, danach
höchstens alle zehn Sekunden sowie beim Erreichen von 100 Prozent.
Die vom Downloader gelieferten Größen-/Geschwindigkeitsangaben werden übernommen.
Terminal-Farbcodes werden entfernt; Fortschrittszeilen mit Wagenrücklauf werden
als einzelne Logzeilen verarbeitet.

`ERROR: File already exists at ...` wird als `[Vorhanden, übersprungen]` angezeigt.
Das bestätigt nur die Existenz, nicht Größe, Prüfsumme oder Aktualität.
Andere Fehler, insbesondere Entschlüsselungsfehler und Verzeichniskonflikte,
bleiben Fehler. Ein Nicht-Null-Exit-Code wird weiterhin als Fehler behandelt.
Während der Ordneranalyse oder ohne Fortschrittsmeldungen des Downloaders
erscheint kein erfundener Prozentwert. Die Zähler beruhen auf Ausgabemeldungen,
nicht auf einem vollständigen Inventar aller Dateien.

### Ungültige Links und Entschlüsselungsfehler

`DEIN_LINK_1` und `SCHLUESSEL_1` sind nur Platzhalter und müssen ersetzt
oder auskommentiert werden. Meldungen wie `Skipping invalid Mega download link`,
`key can't be decrypted` oder `CRITICAL` sind keine bereits vorhandenen Dateien.
Auch bei Exit-Code 0 wird ein solcher Prüflauf als fehlgeschlagen oder
unvollständig gemeldet. Ein erreichtes Transferlimit ist ebenfalls kein Erfolg.

Bei Entschlüsselungsfehlern zuerst den vollständigen Link im MEGA-Webclient
prüfen: Lassen sich die betroffenen Dateien dort anzeigen und herunterladen?
Falls nicht, den Link bzw. Schlüssel beim Freigebenden prüfen lassen.
Falls der Webclient funktioniert, müssen Version und Kompatibilität von
`megatools` untersucht werden. Die Logauswertung repariert keine Dateischlüssel.
Echte Links und Schlüssel nicht in öffentliche Issues oder Logs hochladen.

Die Ausgabezählung erkennt nur eindeutige Meldungen (`already downloaded`,
`Downloaded`). Sie ist kein vollständiger Inhaltsvergleich und erkennt keine
gleich großen Inhaltsänderungen.

Im Unraid-WebUI kannst du jederzeit auf das Icon des Containers klicken und **Protokoll (Logs)** wählen. Die Ausgabe sieht übersichtlich so aus:

```text
[2026-10-12 21:30:00] [INFO] MegaSync Dienst gestartet.
[2026-10-12 21:30:00] [INFO] Konfiguration:
[2026-10-12 21:30:00] [INFO]   - Link-Datei (Unraid): /config/Link.txt
[2026-10-12 21:30:00] [INFO]   - Download-Verzeichnis: /downloads
[2026-10-12 21:30:00] [INFO]   - Täglicher Prüfzeitpunkt: 03:00 Uhr
[2026-10-12 21:30:00] [INFO] === Starte Prüflauf (Link-Datei: /config/Link.txt) ===
[2026-10-12 21:30:00] [INFO] 3 Link(s) gefunden. Starte Abgleich mit '/downloads'...
[2026-10-12 21:30:00] [INFO] [1/3] Prüfe: https://mega.nz/folder/ABC... -> Ziel: /
[2026-10-12 21:30:05] [INFO] [Neu geladen] Downloaded: NeuerFilm.mkv
[2026-10-12 21:30:06] [INFO] [1/3] Erfolgreich abgeglichen (1 neu, 14 bereits aktuell).
[2026-10-12 21:30:06] [INFO] [2/3] Prüfe: https://mega.nz/folder/DEF... -> Ziel: /
[2026-10-12 21:30:08] [INFO] [2/3] Erfolgreich abgeglichen (0 neu, 8 bereits aktuell).
[2026-10-12 21:30:08] [INFO] [3/3] Prüfe: https://mega.nz/folder/GHI... -> Ziel: /
[2026-10-12 21:30:10] [INFO] [3/3] Erfolgreich abgeglichen (0 neu, 22 bereits aktuell).
[2026-10-12 21:30:10] [INFO] === Prüflauf beendet. Gesamt: 1 neu heruntergeladen, 44 bereits vorhanden ===
[2026-10-12 21:30:10] [INFO] Nächster täglicher Prüflauf um 03:00:00 Uhr (in 5h 30m).
```
