#!/usr/bin/env python3
"""
MegaSync for Unraid / Docker
Prüft täglich konfigurierte MEGA-Links, gleicht neue Dateien ab und lädt diese herunter.
Die Links werden bei jedem Durchlauf frisch aus der Textdatei gelesen.
"""

import os
import sys
import time
import signal
import subprocess
import re
import json
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Globale Variable für den Abbruch (SIGTERM / SIGINT)
running = True

def signal_handler(signum, frame):
    global running
    sig_name = signal.Signals(signum).name
    log(f"Signal {sig_name} empfangen. Beende MegaSync sauber...", "INFO")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def log(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if bool(self.token) != bool(self.chat_id):
            log("Telegram deaktiviert: TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID müssen beide gesetzt sein.", "WARN")

    def send(self, message):
        if not self.token or not self.chat_id:
            return
        # 2000 Unicode-Zeichen bleiben auch mit UTF-16-Surrogatpaaren unter dem API-Limit.
        text = message if len(message) <= 2000 else message[:1997] + "..."
        try:
            request = Request(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data=json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                result = json.load(response)
            if not isinstance(result, dict) or result.get("ok") is not True:
                log("Telegram-Nachricht fehlgeschlagen: API meldet keinen Erfolg.", "WARN")
        except HTTPError as exc:
            exc.close()
            log(f"Telegram-Nachricht fehlgeschlagen (HTTP {exc.code}).", "WARN")
        except (URLError, OSError, ValueError):
            # Exception-Texte können die Request-URL mit dem Bot-Token enthalten.
            log("Telegram-Nachricht fehlgeschlagen: Netzwerkfehler oder ungültige API-Antwort.", "WARN")

def parse_time_duration(val_str, default=86400):
    """Parst Zeitangaben wie '86400', '24h', '1d', '30m' in Sekunden."""
    val_str = str(val_str).strip().lower()
    if not val_str:
        return default
    if val_str.endswith("d"):
        return int(float(val_str[:-1]) * 86400)
    elif val_str.endswith("h"):
        return int(float(val_str[:-1]) * 3600)
    elif val_str.endswith("m"):
        return int(float(val_str[:-1]) * 60)
    elif val_str.endswith("s"):
        return int(float(val_str[:-1]))
    try:
        return int(val_str)
    except ValueError:
        log(f"Ungültige Zeitangabe '{val_str}', verwende Standard: {default}s", "WARN")
        return default

def get_links_file_path():
    """Findet den konfigurierten Pfad zur Link.txt Datei."""
    configured = os.getenv("LINKS_FILE", "/config/Link.txt").strip()
    if os.path.exists(configured):
        return configured
    # Fallbacks für verschiedene Mount-Möglichkeiten
    fallbacks = ["/config/Link.txt", "/Link.txt", "/data/Link.txt"]
    for fb in fallbacks:
        if os.path.exists(fb):
            return fb
    return configured

def ensure_links_file_exists(file_path):
    """Erstellt eine Vorlage-Datei, falls noch keine Link.txt existiert."""
    if not os.path.exists(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        template_content = (
            "# ============================================================\n"
            "# MegaSync - Link Konfiguration\n"
            "# ============================================================\n"
            "# Trage hier deine MEGA-Links ein (ein Link pro Zeile).\n"
            "# Zeilen, die mit '#' beginnen, und Leerzeilen werden ignoriert.\n"
            "#\n"
            "# Optional kannst du einen Ziel-Unterordner angeben:\n"
            "# https://mega.nz/folder/xyz#abc | MeinOrdner\n"
            "#\n"
            "# Beispiele (ersetze diese mit deinen echten Links):\n"
            "# https://mega.nz/folder/EXAMPLE1#KEY1\n"
            "# https://mega.nz/folder/EXAMPLE2#KEY2\n"
            "# https://mega.nz/folder/EXAMPLE3#KEY3\n"
            "# ============================================================\n"
        )
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(template_content)
            log(f"Neue Vorlage für Link-Datei erstellt unter: {file_path}", "INFO")
            log("Bitte bearbeite diese Datei auf deinem Unraid-System und füge deine MEGA-Links ein.", "INFO")
        except Exception as e:
            log(f"Konnte Vorlage-Datei {file_path} nicht erstellen: {e}", "ERROR")

def read_links(file_path):
    """
    Liest die Links frisch aus der Textdatei.
    Gibt eine Liste von Dictionaries zurück: [{'url': ..., 'target_subdir': ...}]
    """
    if not os.path.exists(file_path):
        log(f"Link-Datei nicht gefunden: {file_path}", "WARN")
        ensure_links_file_exists(file_path)
        return []

    links = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                # Kommentare und Leerzeilen überspringen
                if not line or line.startswith("#") or line.startswith("//"):
                    continue

                target_subdir = None
                if "|" in line:
                    parts = line.split("|", 1)
                    url = parts[0].strip()
                    target_subdir = parts[1].strip()
                else:
                    url = line

                # Entferne ggf. angehängte Kommentare
                if " #" in url:
                    url = url.split(" #", 1)[0].strip()

                if url.startswith("https://mega.nz/") or url.startswith("mega://"):
                    links.append({
                        "url": url,
                        "target_subdir": target_subdir,
                        "line": line_no
                    })
                else:
                    log(f"Zeile {line_no}: Ignoriere ungültigen Link (muss mit https://mega.nz/ beginnen): {url}", "WARN")
    except Exception as e:
        log(f"Fehler beim Lesen der Link-Datei '{file_path}': {e}", "ERROR")

    return links

def run_megatools_download(url, dest_dir, extra_options=None, notifier=None):
    """
    Führt 'megatools dl' aus.
    megatools prüft vorhandene Dateien automatisch und lädt nur neue / unvollständige Dateien herunter.
    """
    if notifier is None:
        notifier = TelegramNotifier()
    cmd = [
        "megatools", "dl",
        "--path", dest_dir
    ]

    username = os.getenv("MEGA_USERNAME", "").strip()
    password = os.getenv("MEGA_PASSWORD", "").strip()
    if username and password:
        cmd.extend(["--username", username, "--password", password])

    speed_limit = os.getenv("SPEED_LIMIT", "").strip()
    if speed_limit:
        cmd.extend(["--limit-speed", speed_limit])

    extra_args = os.getenv("EXTRA_ARGS", "").strip()
    if extra_args:
        cmd.extend(extra_args.split())

    cmd.append(url)

    # Sichere Ausgabe des Befehls (Passwort maskieren)
    safe_cmd = []
    skip_next = False
    for arg in cmd:
        if skip_next:
            safe_cmd.append("******")
            skip_next = False
        elif arg == "--password":
            safe_cmd.append(arg)
            skip_next = True
        else:
            safe_cmd.append(arg)

    log(f"Starte Download-Prüfung: {' '.join(safe_cmd)}", "DEBUG")

    downloaded_count = 0
    skipped_count = 0
    existing_file_errors = 0
    quota_reached = False
    error_messages = []
    progress_file = None
    last_progress_time = 0.0
    last_progress_percent = None
    last_telegram_time = None
    last_telegram_percent = None
    completed_file = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        global running
        while running:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line:
                clean_line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
                if not clean_line:
                    continue

                lower_line = clean_line.lower()
                progress = re.match(r"^(.+?):\s*(\d{1,3}(?:\.\d+)?)%\s*-\s*(done\b)?", clean_line)
                file_start = re.match(r"^F (/.+)$", clean_line)
                if re.match(r"^(?:ERROR|WARNING): File already exists at .+", clean_line, re.IGNORECASE):
                    skipped_count += 1
                    existing_file_errors += 1
                    log(f"[Vorhanden, übersprungen] {clean_line.split(':', 1)[1].strip()}", "INFO")
                elif file_start:
                    progress_file = os.path.basename(file_start.group(1))
                    last_progress_time = 0.0
                    last_progress_percent = None
                    last_telegram_time = None
                    last_telegram_percent = None
                    completed_file = None
                    log(f"[Download gestartet] {file_start.group(1)}", "INFO")
                    notifier.send(f"MegaSync: Download gestartet: {progress_file}")
                elif progress and progress.group(3) and float(progress.group(2)) <= 100:
                    downloaded_count += 1
                    completed_file = progress.group(1)
                    log(f"[Neu geladen] {clean_line}", "INFO")
                    notifier.send(f"MegaSync: Download abgeschlossen: {clean_line}")
                elif progress and float(progress.group(2)) <= 100:
                    filename = progress.group(1)
                    percent = float(progress.group(2))
                    now = time.monotonic()
                    if filename != progress_file:
                        progress_file = filename
                        last_progress_time = 0.0
                        last_progress_percent = None
                        last_telegram_time = None
                        last_telegram_percent = None
                        completed_file = None
                        notifier.send(f"MegaSync: Neue oder unvollständige Datei wird heruntergeladen: {filename}")
                    if (last_telegram_time is None
                            or now - last_telegram_time >= 60
                            or (percent >= 100 and last_telegram_percent != percent)):
                        notifier.send(f"MegaSync: Download-Fortschritt: {clean_line}")
                        last_telegram_time = now
                        last_telegram_percent = percent
                    if (last_progress_percent is None
                            or now - last_progress_time >= 10
                            or (percent >= 100 and last_progress_percent != percent)):
                        log(f"[Fortschritt] {clean_line}", "INFO")
                        last_progress_time = now
                        last_progress_percent = percent
                elif any(q in lower_line for q in ("bandwidth limit", "transfer quota exceeded", "over quota", "509")):
                    if not quota_reached:
                        notifier.send("MegaSync: MEGA-Transferlimit erreicht. Der Download wird im nächsten Prüflauf erneut versucht.")
                    quota_reached = True
                    log(f"[Limit] MEGA Bandbreiten-Limit erreicht: {clean_line}", "WARN")
                elif any(marker in lower_line for marker in (
                    "warning:", "error", "failed", "critical", "can't be decrypted",
                )):
                    error_messages.append(clean_line)
                    log(f"[Fehler] {clean_line}", "ERROR")
                elif "already downloaded" in lower_line:
                    skipped_count += 1
                    log(f"[Geprüft] {clean_line}", "DEBUG")
                elif "Skipping" in clean_line:
                    error_messages.append(clean_line)
                    log(f"[Nicht abgeglichen] {clean_line}", "WARN")
                elif "Downloaded" in clean_line:
                    if completed_file is not None:
                        # Einzeldatei-Links melden nach der "done"-Zeile zusätzlich "Downloaded".
                        log(f"  {clean_line}", "DEBUG")
                        completed_file = None
                    else:
                        downloaded_count += 1
                        log(f"[Neu geladen] {clean_line}", "INFO")
                        notifier.send(f"MegaSync: Download abgeschlossen: {clean_line}")
                else:
                    log(f"  {clean_line}", "INFO")

        if not running and proc.poll() is None:
            log("Beende laufenden Download-Prozess...", "INFO")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return False, 0, 0

        rc = proc.wait()
        existing_files_only = rc == 1 and existing_file_errors > 0
        if (rc == 0 or existing_files_only) and not error_messages and not quota_reached:
            if existing_files_only:
                log("megatools meldet Statuscode 1 wegen vorhandener Dateien; keine weiteren Fehler gemeldet. "
                    "Vorhandene Dateien wurden nicht auf Vollständigkeit geprüft.", "INFO")
            return True, downloaded_count, skipped_count
        else:
            if quota_reached:
                log("MEGA Quota/Bandbreitenlimit erreicht. Fehlende Dateien werden im nächsten Zyklus fortgesetzt.", "WARN")
            elif error_messages:
                log(f"Download mit Statuscode {rc} beendet. Details: {' | '.join(error_messages[-3:])}", "WARN")
            else:
                log(f"Download mit Statuscode {rc} beendet.", "WARN")
            return False, downloaded_count, skipped_count

    except Exception as e:
        log(f"Ausnahmefehler bei megatools: {e}", "ERROR")
        return False, downloaded_count, skipped_count

def process_links(links_file, base_download_dir):
    """Liest Links frisch ein und gleicht jeden Link ab."""
    log(f"=== Starte Prüflauf (Link-Datei: {links_file}) ===", "INFO")
    links = read_links(links_file)

    if not links:
        log(f"Keine aktiven MEGA-Links in '{links_file}' gefunden.", "WARN")
        log("Trage Links in die Datei ein. Der Prüflauf wird wiederholt, sobald Links eingetragen sind.", "INFO")
        return 0

    log(f"{len(links)} Link(s) gefunden. Starte Abgleich mit '{base_download_dir}'...", "INFO")
    os.makedirs(base_download_dir, exist_ok=True)
    notifier = TelegramNotifier()
    notifier.send(f"MegaSync: Prüflauf gestartet ({len(links)} Links).")

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    for idx, item in enumerate(links, start=1):
        if not running:
            log("Abgleich durch Benutzer abgebrochen.", "WARN")
            break

        url = item["url"]
        subdir = item["target_subdir"]
        dest = os.path.join(base_download_dir, subdir) if subdir else base_download_dir
        os.makedirs(dest, exist_ok=True)

        target_display = f"/{subdir}" if subdir else "/"
        log(f"[{idx}/{len(links)}] Prüfe: {url} -> Ziel: {target_display}", "INFO")

        success, dl_count, skip_count = run_megatools_download(url, dest, notifier=notifier)
        total_downloaded += dl_count
        total_skipped += skip_count

        if success:
            log(f"[{idx}/{len(links)}] Prüflauf erfolgreich ({dl_count} Download-Abschlüsse gemeldet, {skip_count} vorhanden/übersprungen).", "INFO")
        else:
            total_failed += 1
            log(f"[{idx}/{len(links)}] Abgleich fehlgeschlagen oder unvollständig; nicht alle Dateien wurden geladen.", "ERROR")
            notifier.send(f"MegaSync: Link {idx}/{len(links)} fehlgeschlagen oder unvollständig. Details im Container-Log.")

    log(f"=== Prüflauf beendet. Gesamt: {total_downloaded} Download-Abschlüsse gemeldet, {total_skipped} vorhanden/übersprungen ===", "INFO")
    status = "beendet" if running else "abgebrochen"
    notifier.send(
        f"MegaSync: Prüflauf {status}. {total_downloaded} Download-Abschlüsse gemeldet, "
        f"{total_skipped} vorhanden/übersprungen, {total_failed} Links fehlgeschlagen/unvollständig."
    )
    return len(links)

def calculate_sleep_seconds():
    """
    Berechnet die Wartezeit bis zum nächsten Prüflauf.
    Unterstützt SCAN_TIME (z.B. '03:00') für feste Uhrzeiten oder SCAN_INTERVAL (Standard: 86400s = 1 Tag).
    """
    scan_time_str = os.getenv("SCAN_TIME", "").strip()

    if scan_time_str:
        # Feste tägliche Uhrzeit z.B. "03:00" oder "04:30"
        match = re.match(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$", scan_time_str)
        if match:
            target_hour = int(match.group(1))
            target_minute = int(match.group(2))
            now = datetime.now()
            target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if target <= now:
                # Liegt heute schon in der Vergangenheit -> morgen
                target += timedelta(days=1)
            sleep_sec = (target - now).total_seconds()
            hours, remainder = divmod(int(sleep_sec), 3600)
            minutes, seconds = divmod(remainder, 60)
            log(f"Nächster täglicher Prüflauf um {target.strftime('%H:%M:%S')} Uhr (in {hours}h {minutes}m).", "INFO")
            return sleep_sec
        else:
            log(f"Ungültiges SCAN_TIME Format '{scan_time_str}'. Erwartet: HH:MM (z.B. 03:00). Verwende SCAN_INTERVAL.", "WARN")

    # Intervall-Modus (Standard: 86400 = 24h)
    interval_raw = os.getenv("SCAN_INTERVAL", "86400")
    interval = parse_time_duration(interval_raw, default=86400)
    hours, remainder = divmod(interval, 3600)
    minutes, seconds = divmod(remainder, 60)
    next_run = datetime.now() + timedelta(seconds=interval)
    log(f"Nächster Prüflauf geplant für {next_run.strftime('%Y-%m-%d %H:%M:%S')} (Intervall: {hours}h {minutes}m).", "INFO")
    return interval

def sleep_interruptible(seconds):
    """Schläft die angegebene Zeit, reagiert aber sofort auf SIGTERM / SIGINT."""
    global running
    end_time = time.time() + seconds
    while running and time.time() < end_time:
        time.sleep(min(1.0, end_time - time.time()))

def main():
    log("MegaSync Dienst gestartet.", "INFO")
    links_file = get_links_file_path()
    download_dir = os.getenv("DOWNLOAD_DIR", "/downloads").strip()
    run_on_startup = os.getenv("RUN_ON_STARTUP", "true").lower() in ("true", "1", "yes")

    log(f"Konfiguration:", "INFO")
    log(f"  - Link-Datei (Unraid): {links_file}", "INFO")
    log(f"  - Download-Verzeichnis: {download_dir}", "INFO")
    if os.getenv("SCAN_TIME"):
        log(f"  - Täglicher Prüfzeitpunkt: {os.getenv('SCAN_TIME')} Uhr", "INFO")
    else:
        log(f"  - Prüf-Intervall: {os.getenv('SCAN_INTERVAL', '86400')}s (täglich)", "INFO")

    ensure_links_file_exists(links_file)

    first_run = True
    while running:
        if first_run:
            if run_on_startup:
                count = process_links(links_file, download_dir)
                if count == 0:
                    # Wenn noch keine Links eingetragen wurden, nicht 24h warten, sondern alle 60s prüfen
                    log("Warte auf Links in 'Link.txt'... (nächste Prüfung in 60 Sekunden)", "INFO")
                    sleep_interruptible(60)
                    continue
            first_run = False
        else:
            count = process_links(links_file, download_dir)
            if count == 0:
                log("Warte auf Links in 'Link.txt'... (nächste Prüfung in 60 Sekunden)", "INFO")
                sleep_interruptible(60)
                continue

        if not running:
            break

        sleep_time = calculate_sleep_seconds()
        sleep_interruptible(sleep_time)

    log("MegaSync wurde beendet.", "INFO")

if __name__ == "__main__":
    main()
