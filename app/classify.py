"""Nachgelagerte Fahrzeug-Klassifizierung der Ereignis-Snapshots.

Bewusst NICHT in der Echtzeit-Pipeline (dafuer war YOLO auf dem J4105 zu
langsam), sondern einmal pro gespeichertem Ereignis in einem
Hintergrund-Thread: Das Rohbild wird klassifiziert, die Erkennung mit der
groessten Ueberlappung zur Mess-Box gewaehlt und die Klasse nachtraeglich
in die Datenbank geschrieben.

Benoetigt das optionale Paket "ultralytics" (inkl. Torch-CPU). Fehlt es,
bleibt die Klassifizierung stumm deaktiviert und alles andere laeuft normal.
"""
from __future__ import annotations

import logging
import queue
import threading

log = logging.getLogger("trafficcam.classify")

# COCO-Klassen -> deutsche Labels (Rest wird "Sonstige")
COCO_LABELS = {
    0: "Fussgaenger",
    1: "Fahrrad",
    2: "PKW",
    3: "Motorrad",
    5: "Bus",
    7: "LKW",
}


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(area_a + area_b - inter, 1e-9)


class SnapshotClassifier(threading.Thread):
    """Worker-Thread: nimmt (event_id, frame, bbox) an, schreibt Klasse."""

    def __init__(self, storage, model="yolo11n.pt", conf=0.35, imgsz=640):
        super().__init__(daemon=True, name="snapshot-classifier")
        self.storage = storage
        self.model_name = model
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.queue = queue.Queue(maxsize=50)
        self.available = None      # None = noch nicht geladen
        self._model = None

    def submit(self, event_id, frame, bbox):
        if self.available is False:
            return
        try:
            self.queue.put_nowait((event_id, frame.copy(), list(bbox)))
        except queue.Full:
            log.warning("Klassifizierungs-Queue voll - Ereignis %s "
                        "uebersprungen", event_id)

    def _ensure_model(self):
        if self._model is not None:
            return True
        if self.available is False:
            return False
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_name)
            self.available = True
            log.info("Snapshot-Klassifizierung aktiv (%s)", self.model_name)
            return True
        except Exception as e:
            self.available = False
            log.warning("Klassifizierung deaktiviert: %s "
                        "(pip install ultralytics)", e)
            return False

    def classify_frame(self, frame, bbox):
        """Ein Bild klassifizieren -> Label (immer ein String)."""
        if not self._ensure_model():
            return "Fahrzeug"
        try:
            res = self._model.predict(frame, conf=self.conf,
                                      imgsz=self.imgsz, verbose=False)[0]
            best_label, best_iou = "Sonstige", 0.05   # Mindest-Ueberlappung
            for box, cls in zip(res.boxes.xyxy.tolist(),
                                res.boxes.cls.tolist()):
                label = COCO_LABELS.get(int(cls))
                if label is None:
                    continue
                overlap = _iou(box, bbox)
                if overlap > best_iou:
                    best_iou, best_label = overlap, label
            return best_label
        except Exception as e:
            log.warning("Klassifizierung fehlgeschlagen: %s", e)
            return "Sonstige"

    def run(self):
        while True:
            event_id, frame, bbox = self.queue.get()
            label = self.classify_frame(frame, bbox)
            try:
                self.storage.update_class(event_id, label)
            except Exception as e:
                log.warning("Klasse konnte nicht gespeichert werden: %s", e)
