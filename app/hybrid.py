"""Erweiterte Erfassung: asynchroner KI-Anker-Worker (Hybrid-Modus).

Konzept: Die Bewegungserkennung (MOG2) bleibt der Echtzeit-Tracker bei
voller Framerate. Dieser Worker bekommt - entkoppelt, mit
Neuestes-gewinnt-Semantik - einzelne Frames samt der aktiven Track-Boxen
angeboten, laesst YOLO auf dem Messbereich-Ausschnitt laufen und liefert
korrigierte, beleuchtungsunabhaengige Fahrzeug-Boxen ("Anker") zurueck.
Die Pipeline rechnet daraus Bodenmesspunkte mit dem Aufnahme-Zeitstempel
des Frames; die Geschwindigkeitsmessung stuetzt sich bevorzugt auf diese
Anker (siehe pipeline._finalize).

Auslegung nach Benchmark auf dem Referenzsystem (Intel J4105):
Ausschnitt @ Netz 320 = ~78 ms/Bild -> 4-6 Anker pro Durchfahrt, waehrend
MOG2 ungestoert weiterlaeuft. Benoetigt "ultralytics" (wie Klassifizierung
und Benchmark); fehlt es, meldet sich der Worker ab und die Messung laeuft
unveraendert im einfachen Modus weiter.
"""
from __future__ import annotations

import logging
import threading
import time

from .classify import COCO_LABELS, _iou

log = logging.getLogger("trafficcam.hybrid")


def zone_rect(frame_shape, zone, margin=0.15):
    """Ausschnitt-Rechteck (x1,y1,x2,y2) um den Messbereich.

    Nach oben um ein Mehrfaches der Bandhoehe erweitert (Fahrzeughoehe -
    der Messbereich selbst ist ein flaches Band auf der Fahrbahn).
    """
    xs = [p[0] for p in zone]
    ys = [p[1] for p in zone]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    zh = max(y2 - y1, 8)
    mx = (x2 - x1) * margin
    h, w = frame_shape[:2]
    x1 = max(0, int(x1 - mx)); x2 = min(w, int(x2 + mx))
    y1 = max(0, int(y1 - 2.5 * zh))
    y2 = min(h, int(y2 + zh * margin))
    if x2 - x1 < 32 or y2 - y1 < 32:
        return None
    return (x1, y1, x2, y2)


class HybridAnchorWorker(threading.Thread):
    """Nimmt Frames an (neuester gewinnt), liefert KI-Anker pro Track."""

    def __init__(self, model="yolo11n.pt", conf=0.35, imgsz=320,
                 min_interval=0.15):
        super().__init__(daemon=True, name="hybrid-anchors")
        self.model_name = model
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.min_interval = float(min_interval)
        self.available = None          # None = Modell noch nicht geladen
        self._model = None
        self._lock = threading.Lock()
        self._slot = None              # (ts, frame, tracks, rect)
        self._results = []             # [(tid, ts, bbox_vollbild)]
        self._wake = threading.Event()
        self._busy = False
        self._last_start = 0.0
        self.inference_ms = None       # letzte Inferenzdauer (Diagnose)

    # ---- Pipeline-Seite (nicht blockierend) -------------------------------
    def ready_for_frame(self):
        """True, wenn ein neues Angebot sinnvoll ist (idle + Intervall)."""
        if self.available is False:
            return False
        with self._lock:
            if self._busy or self._slot is not None:
                return False
        return (time.monotonic() - self._last_start) >= self.min_interval

    def offer(self, ts, frame, tracks, rect):
        """tracks: Liste (tid, bbox) in Vollbild-Koordinaten."""
        if self.available is False or not tracks:
            return
        with self._lock:
            self._slot = (ts, frame.copy(), list(tracks), rect)
        self._wake.set()

    def collect(self):
        with self._lock:
            out = self._results
            self._results = []
            return out

    # ---- Worker-Seite ------------------------------------------------------
    def _ensure_model(self):
        if self._model is not None:
            return True
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_name)
            self.available = True
            log.info("Erweiterte Erfassung aktiv (%s, imgsz=%d)",
                     self.model_name, self.imgsz)
            return True
        except Exception as e:
            self.available = False
            log.warning("Erweiterte Erfassung nicht verfuegbar: %s "
                        "(pip install ultralytics) - Messung laeuft im "
                        "einfachen Modus weiter", e)
            return False

    def _detect(self, frame, rect):
        """YOLO auf dem Ausschnitt; Boxen in Vollbild-Koordinaten."""
        ox, oy = 0, 0
        img = frame
        if rect is not None:
            x1, y1, x2, y2 = rect
            img = frame[y1:y2, x1:x2]
            ox, oy = x1, y1
        res = self._model.predict(img, conf=self.conf, imgsz=self.imgsz,
                                  verbose=False)[0]
        out = []
        for box, cls in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist()):
            if int(cls) not in COCO_LABELS:
                continue
            out.append([box[0] + ox, box[1] + oy,
                        box[2] + ox, box[3] + oy])
        return out

    def run(self):
        while True:
            self._wake.wait()
            with self._lock:
                item = self._slot
                self._slot = None
                self._wake.clear()
                if item is None:
                    continue
                self._busy = True
            self._last_start = time.monotonic()
            try:
                if not self._ensure_model():
                    return                     # dauerhaft abmelden
                ts, frame, tracks, rect = item
                t0 = time.monotonic()
                dets = self._detect(frame, rect)
                self.inference_ms = round(
                    (time.monotonic() - t0) * 1000.0, 1)
                matched = []
                for tid, tb in tracks:
                    best, best_iou = None, 0.20   # strenger: verhindert
                    # Fehl-Matches auf geparkte Fahrzeuge bei aufgeblaehter
                    # MOG2-Box (Schatten/Scheinwerferkegel)
                    for db in dets:
                        ov = _iou(db, tb)
                        if ov > best_iou:
                            best_iou, best = ov, db
                    if best is not None:
                        matched.append((tid, ts, best))
                if matched:
                    with self._lock:
                        self._results.extend(matched)
                        # Ergebnis-Puffer begrenzen
                        if len(self._results) > 200:
                            self._results = self._results[-200:]
            except Exception as e:
                log.warning("Hybrid-Anker fehlgeschlagen: %s", e)
            finally:
                with self._lock:
                    self._busy = False
