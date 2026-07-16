"""KI-Benchmark: misst, wie schnell YOLO auf dieser Maschine laeuft.

Entscheidungshilfe fuer die Frage "einfache oder erweiterte Erfassung?":
Der Benchmark laeuft im Hintergrund WAEHREND die normale Erkennung
weiterarbeitet - die Zahlen entstehen also unter realer Last und sind
direkt belastbar. Getestet werden Vollbild und (falls ein Messbereich
definiert ist) der zugeschnittene Ausschnitt in mehreren Aufloesungen.

Benoetigt das optionale Paket "ultralytics" (wie die Klassifizierung).
"""
from __future__ import annotations

import logging
import statistics
import threading
import time

log = logging.getLogger("trafficcam.benchmark")


def _einordnung(fps):
    if fps >= 25:
        return "Voll-KI je Frame in Echtzeit m\u00f6glich"
    if fps >= 10:
        return "KI je Frame mit reduzierter Rate machbar"
    if fps >= 3:
        return "Hybrid empfohlen: KI-Boxkorrektur alle paar Frames"
    return "nur f\u00fcr Snapshot-Klassifizierung geeignet"


def crop_to_zone(frame, zone, margin=0.15):
    """Messbereich-Ausschnitt (inkl. Fahrzeughoehe nach oben).

    Rechteck-Logik liegt in hybrid.zone_rect und wird von Benchmark und
    erweiterter Erfassung gemeinsam genutzt.
    """
    from .hybrid import zone_rect
    rect = zone_rect(frame.shape, zone, margin)
    if rect is None:
        return None
    x1, y1, x2, y2 = rect
    return frame[y1:y2, x1:x2]


class BenchmarkRunner:
    def __init__(self, model="yolo11n.pt", conf=0.35):
        self.model_name = model
        self.conf = float(conf)
        self._lock = threading.Lock()
        self.state = "idle"          # idle | running | done | error
        self.progress = ""
        self.results = []
        self.error = None
        self.load_s = None

    def status(self):
        with self._lock:
            return {"state": self.state, "progress": self.progress,
                    "results": list(self.results), "error": self.error,
                    "model": self.model_name, "load_s": self.load_s}

    def start(self, frame, zone=None):
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.progress = "Modell wird geladen \u2026"
            self.results = []
            self.error = None
            self.load_s = None
        t = threading.Thread(target=self._run, args=(frame, zone),
                             daemon=True, name="ki-benchmark")
        t.start()
        return True

    # ---- intern ----------------------------------------------------------
    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _run(self, frame, zone):
        try:
            try:
                from ultralytics import YOLO
            except Exception:
                self._set(state="error", progress="", error=(
                    "ultralytics ist nicht installiert. Installation: "
                    "sudo /opt/trafficcam/.venv/bin/pip install torch "
                    "torchvision --index-url "
                    "https://download.pytorch.org/whl/cpu && sudo "
                    "/opt/trafficcam/.venv/bin/pip install ultralytics"))
                return
            t0 = time.monotonic()
            model = YOLO(self.model_name)
            # Variantenliste: (Name, Bild, imgsz)
            variants = [("Vollbild", frame, 640),
                        ("Vollbild, kleine Aufl\u00f6sung", frame, 416)]
            if zone:
                crop = crop_to_zone(frame, zone)
                if crop is not None:
                    variants += [
                        ("Messbereich-Ausschnitt", crop, 416),
                        ("Messbereich-Ausschnitt, klein", crop, 320)]
            # ein Warmlauf initialisiert alles (zaehlt zur Ladezeit)
            model.predict(frame, conf=self.conf, imgsz=640, verbose=False)
            self._set(load_s=round(time.monotonic() - t0, 1))

            out = []
            for i, (name, img, imgsz) in enumerate(variants, 1):
                self._set(progress=f"Variante {i}/{len(variants)}: {name}")
                model.predict(img, conf=self.conf, imgsz=imgsz,
                              verbose=False)          # Warmup je Variante
                times = []
                for _ in range(8):
                    t1 = time.monotonic()
                    model.predict(img, conf=self.conf, imgsz=imgsz,
                                  verbose=False)
                    times.append(time.monotonic() - t1)
                ms = statistics.median(times) * 1000.0
                fps = 1000.0 / ms if ms > 0 else 0.0
                out.append({"variante": name,
                            "bild": f"{img.shape[1]}\u00d7{img.shape[0]}",
                            "imgsz": imgsz,
                            "ms": round(ms, 1),
                            "fps": round(fps, 1),
                            "einordnung": _einordnung(fps)})
                with self._lock:
                    self.results = list(out)
            self._set(state="done", progress="")
        except Exception as e:
            log.warning("Benchmark fehlgeschlagen: %s", e)
            self._set(state="error", progress="", error=str(e))
