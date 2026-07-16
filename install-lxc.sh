#!/usr/bin/env bash
set -euo pipefail

# TrafficCam - native Installation auf Debian/Ubuntu (LXC oder Bare Metal).
# Als root im Projektverzeichnis ausfuehren (dort, wo run.py liegt):
#   chmod +x install-lxc.sh && sudo ./install-lxc.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
PYBIN="${PYBIN:-python3}"

echo ">>> Systempakete installieren ..."
apt-get update
apt-get install -y --no-install-recommends \
    "$PYBIN" python3-venv python3-dev build-essential \
    ffmpeg libgl1 libglib2.0-0 ca-certificates

echo ">>> Virtuelle Umgebung anlegen (umgeht PEP-668 auf Debian 12 / Ubuntu 24) ..."
"$PYBIN" -m venv "$DIR/.venv"
# shellcheck disable=SC1091
source "$DIR/.venv/bin/activate"
pip install --upgrade pip wheel

echo ">>> Abhaengigkeiten installieren ..."
pip install -r "$DIR/requirements.txt"

echo ">>> Verzeichnisse + Konfiguration ..."
mkdir -p "$DIR/config" "$DIR/data/snapshots"
if [ ! -f "$DIR/config/config.yaml" ]; then
    # Docker-Pfade (/data, /config) auf das Installationsverzeichnis umbiegen
    sed -e "s#/data/#$DIR/data/#g" -e "s#/config/#$DIR/config/#g" \
        "$DIR/config/config.example.yaml" > "$DIR/config/config.yaml"
    echo "    -> config/config.yaml erstellt, Pfade auf $DIR angepasst."
    echo "    -> WICHTIG: stream.url (und ggf. mqtt) noch eintragen!"
else
    echo "    -> config/config.yaml existiert bereits, unveraendert gelassen."
fi

echo ">>> systemd-Service installieren ..."
cat > /etc/systemd/system/trafficcam.service << UNIT
[Unit]
Description=TrafficCam Verkehrsueberwachung
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
Environment=CONFIG=$DIR/config/config.yaml
ExecStart=$DIR/.venv/bin/python $DIR/run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

echo
echo "=== Fertig ==="
echo "1) Konfig bearbeiten:   nano $DIR/config/config.yaml   (stream.url!)"
echo "2) Starten + Autostart: systemctl enable --now trafficcam"
echo "3) Logs verfolgen:      journalctl -u trafficcam -f"
echo "4) Weboberflaeche:      http://<host-ip>:8088/"
