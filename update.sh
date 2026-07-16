#!/usr/bin/env bash
set -euo pipefail

# TrafficCam Update-Skript
# Sichert Config, Daten und die venv, entpackt ein neues Release-Archiv
# und stellt alles wieder her. Danach wird der Dienst neu gestartet.
#
# Nutzung:
#   ./update.sh /pfad/zur/trafficcam.tar.gz
#   ./update.sh                              # sucht trafficcam.tar.gz im Home-Verzeichnis
#
# Konfigurierbar per Umgebungsvariable (Defaults passen fuer den Standard-Setup):
#   INSTALL_DIR=/opt/trafficcam SERVICE=trafficcam ./update.sh archiv.tar.gz

INSTALL_DIR="${INSTALL_DIR:-/opt/trafficcam}"
SERVICE="${SERVICE:-trafficcam}"
TARBALL="${1:-$HOME/trafficcam.tar.gz}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${INSTALL_DIR}.bak-${STAMP}"

# Als root ausfuehren; falls nicht, automatisch mit sudo neu starten.
if [ "$(id -u)" -ne 0 ]; then
    exec sudo -E "$0" "$@"
fi

echo ">>> TrafficCam Update"
echo "    Archiv:      $TARBALL"
echo "    Zielordner:  $INSTALL_DIR"
echo "    Dienst:      $SERVICE"
echo

if [ ! -f "$TARBALL" ]; then
    echo "FEHLER: Archiv nicht gefunden: $TARBALL" >&2
    echo "Aufruf: $0 /pfad/zur/trafficcam.tar.gz" >&2
    exit 1
fi

# Grobe Plausibilitaetspruefung: enthaelt das Archiv einen trafficcam/-Ordner?
if ! tar -tzf "$TARBALL" | grep -q '^trafficcam/run\.py$'; then
    echo "FEHLER: $TARBALL sieht nicht wie ein TrafficCam-Release aus" >&2
    echo "(erwartet wird ein Ordner 'trafficcam/' mit run.py darin)" >&2
    exit 1
fi

has_service() {
    systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}\.service"
}

if has_service; then
    echo ">>> Stoppe $SERVICE ..."
    systemctl stop "$SERVICE"
else
    echo ">>> Hinweis: systemd-Dienst '$SERVICE' existiert noch nicht - wird uebersprungen"
    echo "    (fuer eine Erstinstallation bitte install-lxc.sh verwenden)"
fi

if [ -d "$INSTALL_DIR" ]; then
    echo ">>> Sichere aktuelle Installation nach $BACKUP_DIR ..."
    mv "$INSTALL_DIR" "$BACKUP_DIR"
else
    echo ">>> Kein bestehender Ordner unter $INSTALL_DIR - reine Neuinstallation"
    BACKUP_DIR=""
fi

echo ">>> Entpacke neues Release ..."
PARENT_DIR="$(dirname "$INSTALL_DIR")"
mkdir -p "$PARENT_DIR"
tar -xzf "$TARBALL" -C "$PARENT_DIR"
# Archiv entpackt nach $PARENT_DIR/trafficcam - falls INSTALL_DIR anders heisst, umbenennen
if [ "$PARENT_DIR/trafficcam" != "$INSTALL_DIR" ]; then
    mv "$PARENT_DIR/trafficcam" "$INSTALL_DIR"
fi

if [ -n "$BACKUP_DIR" ]; then
    echo ">>> Stelle Konfiguration und Daten wieder her ..."
    mkdir -p "$INSTALL_DIR/config"
    for f in config.yaml homography.yaml settings.yaml; do
        if [ -f "$BACKUP_DIR/config/$f" ]; then
            cp "$BACKUP_DIR/config/$f" "$INSTALL_DIR/config/$f"
            echo "    - config/$f wiederhergestellt"
        fi
    done
    if [ -d "$BACKUP_DIR/data" ]; then
        cp -r "$BACKUP_DIR/data" "$INSTALL_DIR/"
        echo "    - data/ wiederhergestellt"
    fi

    if [ -d "$BACKUP_DIR/.venv" ]; then
        echo ">>> Uebernehme bestehende Python-Umgebung (venv) ..."
        mv "$BACKUP_DIR/.venv" "$INSTALL_DIR/.venv"
        echo ">>> Pruefe auf neue/aktualisierte Abhaengigkeiten ..."
        "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" \
            || echo "    WARNUNG: pip install meldete einen Fehler - bitte Log oben pruefen"
    else
        echo "!!! Keine venv im Backup gefunden - bitte install-lxc.sh erneut ausfuehren"
    fi
else
    echo ">>> Keine alte Installation vorhanden - bitte config/config.yaml anlegen"
    echo "    und install-lxc.sh fuer die Erstinstallation der venv ausfuehren."
fi

if has_service; then
    echo ">>> Starte $SERVICE ..."
    systemctl start "$SERVICE"
    sleep 2
    echo
    echo ">>> Letzte Logzeilen:"
    journalctl -u "$SERVICE" -n 20 --no-pager
fi

echo
echo "=== Update abgeschlossen ==="
if [ -n "$BACKUP_DIR" ]; then
    echo "Alte Version liegt zur Sicherheit noch in: $BACKUP_DIR"
    echo "Wenn alles laeuft, kann sie geloescht werden: rm -rf $BACKUP_DIR"
fi
echo "Live-Logs verfolgen: journalctl -u $SERVICE -f"
