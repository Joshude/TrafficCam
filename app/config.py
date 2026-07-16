"""Konfiguration laden und mit Defaults zusammenführen."""
from __future__ import annotations

import copy
import os
import threading

import yaml

DEFAULTS = {
    "stream": {
        # RTSP-URL der UniFi G4 Doorbell. Sub-/Low-Stream empfohlen (weniger CPU).
        "url": "rtsp://USER:PASS@CAMERA_IP:554/STREAM_ID",
        "rtsp_transport": "tcp",   # tcp ist stabiler als udp
        "reconnect_delay": 3.0,    # Sekunden Backoff bei Verbindungsabbruch
        "target_fps": 0,           # 0 = so schnell wie das Modell schafft
    },
    "motion": {
        "proc_width": 640,     # Breite fuer die Bewegungsanalyse (klein = schnell)
        "min_area": 350,       # Mindestflaeche eines Bewegungs-Blobs (px, skaliert)
        "var_threshold": 32,   # Empfindlichkeit: hoeher = weniger Rauschen erkannt
        "shadow_threshold": 0.3,  # 0..1: kleiner = auch harte Schatten ignorieren
        "tighten_min_fill": 0.15,  # Zeile zaehlt zur Box ab diesem Fuellgrad
                                   # (hoeher = Unterkante klebt fester am Auto)
        "merge_gap": 12,       # nahe Blobs zu einem Objekt zusammenfassen (px)
        "max_dist_frac": 0.18, # max. Sprungweite pro Frame (Anteil Bildbreite)
        "max_missed": 10,      # Frames ohne Sichtung -> Track abschliessen
        "min_hits": 2,         # Mindest-Sichtungen, bevor ein Track zaehlt
    },
    "detector": {
        "erfassung": "einfach",       # "einfach" (MOG2) oder "erweitert"
                                      # (KI-Hybrid: MOG2-Tracking + YOLO-Anker;
                                      # benoetigt ultralytics, siehe Benchmark)
        "hybrid_imgsz": 320,          # Netzgroesse fuer den KI-Ausschnitt
        "hybrid_intervall_s": 0.15,   # Mindestabstand zwischen KI-Laeufen
        "classify_snapshots": False,  # Snapshots nachtraeglich klassifizieren
                                      # (benoetigt: pip install ultralytics)
        "model": "yolo11n.pt",     # nano = schnellste Variante. Auch openvino-Pfad moeglich.
        "device": "cpu",           # "cpu", "0" (CUDA), oder OpenVINO-Modellpfad
        "imgsz": 640,
        "conf": 0.35,
        "iou": 0.5,
        "tracker": "bytetrack.yaml",
        # COCO-Klassen, die uns interessieren -> deutsches Label
        "classes": {
            0: "Fußgänger",
            1: "Fahrrad",
            2: "Auto",
            3: "Roller/Motorrad",
            5: "Bus",
            7: "LKW",
        },
    },
    "speed": {
        "min_samples": 5,      # Mindestanzahl Messpunkte pro Fahrzeug
        "min_time": 0.20,      # Mindest-Messdauer in Sekunden
        "min_disp": 1.5,       # Mindest-Strecke in Metern (gegen Standzeug-Jitter)
        "max_kmh": 200,        # alles darueber gilt als Fehlmessung
        "max_residual_m": 0.6, # max. Fit-Restfehler; drueber = Track-Geist
        "track_max_age": 15,   # Frames ohne Sichtung -> Track abschliessen
    },
    "motion_dusk": {
        "enabled": False,           # Daemmerungs-Profil automatisch aktivieren
        "vor_sonnenuntergang_min": 60,
        "nach_sonnenaufgang_min": 60,
        "var_threshold": 18,        # empfindlicher: Reifen vs. dunkle Fahrbahn
        "shadow_threshold": 0.5,    # dunkle Fahrzeugteile NICHT als Schatten werten
        "tighten_min_fill": 0.12,   # duenn belegte Radzeilen behalten
    },
    "motion_nacht": {
        "enabled": False,          # Nacht-Profil (IR-Bild, Scheinwerferkegel)
        "nach_sonnenuntergang_min": 45,   # ab dann gilt Nacht statt Daemmerung
        "vor_sonnenaufgang_min": 45,
        "var_threshold": 70,       # nur starke Aenderungen (Kegel-Halo raus)
        "shadow_threshold": 0.6,
        "tighten_min_fill": 0.3,   # diffuse Kegelraender abschneiden
        "min_area": 600,           # Streulicht-Fetzen ignorieren
    },
    "zone": None,              # optionales Mess-Polygon [[x,y],...] in Pixeln, oder null
    "storage": {
        "db_path": "/data/events.db",
        "csv_path": "/data/events.csv",
        "save_snapshots": True,
        "snapshot_dir": "/data/snapshots",
    },
    "web": {
        "host": "0.0.0.0",
        "port": 8088,
        "stream_quality": 70,  # JPEG-Qualitaet fuer den Live-Stream
    },
    "mqtt": {
        "enabled": False,
        "host": "localhost",       # IP des MQTT-Brokers (z.B. HA/Mosquitto)
        "port": 1883,
        "username": "",
        "password": "",
        "base_topic": "trafficcam",
        "discovery": True,          # Sensoren automatisch in HA anlegen
        "discovery_prefix": "homeassistant",
    },
    "calibration_file": "/config/homography.yaml",
    "settings_file": None,  # None = neben der calibration_file (settings.yaml)
}


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Thread-sicherer Zugriff auf die Konfiguration inkl. Live-Kalibrierung."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        with self._lock:
            self._data = self._load()

    def _load(self):
        loaded = {}
        if self.path and os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
        cfg = _deep_merge(DEFAULTS, loaded)
        # Klassen-Keys koennen als Strings aus YAML kommen -> zu int
        cfg["detector"]["classes"] = {
            int(k): v for k, v in cfg["detector"]["classes"].items()
        }
        return cfg

    def get(self):
        with self._lock:
            return self._data

    def reload(self):
        with self._lock:
            self._data = self._load()
        return self._data

    def update_values(self, section_updates):
        """Schreibt {sektion: {key: wert}} in die config.yaml und laedt neu.

        Es wird nur die Datei mit den Nutzer-Overrides angefasst; Defaults
        bleiben im Code. Hinweis: yaml.safe_dump verwirft Kommentare in der
        Datei - die dokumentierte Referenz bleibt config.example.yaml.
        """
        with self._lock:
            raw = {}
            if self.path and os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            for section, values in section_updates.items():
                node = raw.setdefault(section, {})
                if not isinstance(node, dict):
                    node = raw[section] = {}
                node.update(values)
            if self.path:
                with open(self.path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(raw, f, allow_unicode=True,
                                   sort_keys=False)
            self._data = self._load()
        return self._data
