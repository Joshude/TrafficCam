"""Zur Laufzeit aenderbare Einstellungen (Web-UI), YAML-persistiert."""
from __future__ import annotations

import os
import threading

import yaml

DEFAULTS = {
    # Filter
    "min_kmh": 10.0,
    "max_kmh": 150.0,
    "tempolimit_kmh": 30.0,      # fuer Statistik (Anteil drueber)
    # Zeitsteuerung des Trackings
    "tracking_mode": "immer",     # immer | zeit | sonne
    "aktiv_von": "06:00",         # bei Modus "zeit"
    "aktiv_bis": "22:00",
    "lat": 53.05,                 # bei Modus "sonne"
    "lon": 8.35,
    "sonnen_offset_min": 0.0,     # +x Min laenger aktiv um Sonnenauf/-untergang
    # Datenpflege: Messungen aelter als X Tage automatisch loeschen (0 = aus)
    "aufbewahrung_tage": 0.0,
    # Live-Overlays
    "show_boxes": True,
    "show_trail": True,
    "show_zone": True,
    "show_line": True,
    "show_mask": False,   # Diagnose: Bewegungsmaske rot einblenden
    # Oberflaechensprache: "de" oder "en"
    "sprache": "de",
}


class Settings:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                for k, dv in DEFAULTS.items():
                    if k in loaded and loaded[k] is not None:
                        self._data[k] = type(dv)(loaded[k])
            except Exception:
                pass

    def get(self):
        with self._lock:
            return dict(self._data)

    def update(self, new):
        with self._lock:
            for k, dv in DEFAULTS.items():
                if k in new and new[k] is not None:
                    self._data[k] = type(dv)(new[k])
            if self.path:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self._data, f)
            return dict(self._data)
