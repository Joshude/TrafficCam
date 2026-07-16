"""Bewegungserkennung (MOG2) + einfacher Centroid-Tracker.

Ersetzt das YOLO-Modell: statt Objekte zu klassifizieren, werden bewegte
Bereiche per Hintergrund-Subtraktion gefunden und ueber Frames verfolgt.
Das ist um Groessenordnungen billiger und laeuft auf schwachen CPUs mit
voller Stream-Framerate.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def _boxes_close(a, b, gap):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 + gap < bx1 or bx2 + gap < ax1
                or ay2 + gap < by1 or by2 + gap < ay1)


def merge_boxes(boxes, gap=12):
    """Fasst nahe/ueberlappende Boxen zusammen (ein Auto = eine Box)."""
    boxes = [list(b) for b in boxes]
    merged = True
    while merged and len(boxes) > 1:
        merged = False
        out = []
        used = [False] * len(boxes)
        for i in range(len(boxes)):
            if used[i]:
                continue
            cur = boxes[i]
            for j in range(i + 1, len(boxes)):
                if used[j]:
                    continue
                if _boxes_close(cur, boxes[j], gap):
                    b = boxes[j]
                    cur = [min(cur[0], b[0]), min(cur[1], b[1]),
                           max(cur[2], b[2]), max(cur[3], b[3])]
                    used[j] = True
                    merged = True
            out.append(cur)
        boxes = out
    return boxes


class MotionDetector:
    def __init__(self, proc_width=640, min_area=350, dilate_iter=2,
                 merge_gap=12, var_threshold=32, shadow_threshold=0.3,
                 tighten_min_fill=0.15):
        self.proc_width = int(proc_width)
        self.min_area = int(min_area)
        self.dilate_iter = int(dilate_iter)
        self.merge_gap = int(merge_gap)
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=float(var_threshold),
            detectShadows=True)
        # MOG2-Default (0.5) haelt nur weiche Schatten fuer Schatten -
        # harte Mittagssonne dunkelt staerker ab und wuerde sonst als
        # Objekt gewertet (Box frisst den Schattenwurf, Bodenpunkt rutscht
        # zur Kamera, Geschwindigkeit wird unterschaetzt).
        self.bg.setShadowThreshold(float(shadow_threshold))
        self.tighten_min_fill = float(tighten_min_fill)
        self.kernel = np.ones((3, 3), np.uint8)
        self.last_mask = None    # Debug: letzte UNdilatierte Maske (proc-Groesse)

    @staticmethod
    def _tighten_vertical(box, raw, min_fill=0.15):
        """Zieht Ober-/Unterkante der Box auf "tragfaehige" Zeilen der
        unaufgeblasenen Maske zusammen.

        Die Bounding-Box wird sonst vom untersten Einzelpixel definiert -
        ein duenner Auslaeufer (Artefakt, dunkler Kontaktschatten) zieht
        die Unterkante und damit den Bodenmesspunkt nach unten. Eine Zeile
        zaehlt erst, wenn ein Mindestanteil der Boxbreite belegt ist.
        """
        x1, y1, x2, y2 = [int(v) for v in box]
        sub = raw[max(y1, 0):y2, max(x1, 0):x2]
        if sub.size == 0:
            return box
        counts = (sub > 0).sum(axis=1)
        need = max(3, int(min_fill * max(x2 - x1, 1)))
        solid = np.nonzero(counts >= need)[0]
        if len(solid) == 0:
            return box
        return [x1, y1 + int(solid[0]), x2, y1 + int(solid[-1]) + 1]

    def detect(self, frame):
        """Liefert Bewegungs-Boxen [x1,y1,x2,y2] in Vollbild-Koordinaten."""
        h, w = frame.shape[:2]
        scale = self.proc_width / float(w)
        small = cv2.resize(frame, (self.proc_width, max(1, int(h * scale))))
        mask = self.bg.apply(small)
        # Schatten (Wert 127) verwerfen, nur harte Bewegung behalten
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        raw = mask                                   # vor der Dilatation!
        self.last_mask = raw
        mask = cv2.dilate(mask, self.kernel, iterations=self.dilate_iter)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            if cv2.contourArea(c) < self.min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            boxes.append([x, y, x + bw, y + bh])
        boxes = merge_boxes(boxes, gap=self.merge_gap)
        boxes = [self._tighten_vertical(b, raw, self.tighten_min_fill)
                 for b in boxes]
        inv = 1.0 / scale
        return [[x1 * inv, y1 * inv, x2 * inv, y2 * inv]
                for x1, y1, x2, y2 in boxes]


class CentroidTracker:
    """Ordnet Bewegungs-Boxen ueber Frames hinweg stabilen IDs zu."""

    def __init__(self, max_dist_frac=0.18, max_missed=10, min_hits=2):
        self.max_dist_frac = max_dist_frac
        self.max_missed = int(max_missed)
        self.min_hits = int(min_hits)
        self._next_id = 1
        self._tracks = {}   # id -> {centroid, bbox, missed, hits}
        self._finished = []

    def update(self, boxes, frame_w):
        """boxes: Vollbild-Boxen. Rueckgabe: Liste {id, bbox} aktiver Tracks."""
        max_dist = self.max_dist_frac * frame_w
        cents = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) for b in boxes]
        unmatched = set(range(len(boxes)))

        # Greedy: jeden bestehenden Track mit naechster Box verheiraten
        pairs = []
        for tid, tr in self._tracks.items():
            best, best_d = None, max_dist
            for i in unmatched:
                d = math.hypot(cents[i][0] - tr["centroid"][0],
                               cents[i][1] - tr["centroid"][1])
                if d < best_d:
                    best, best_d = i, d
            if best is not None:
                pairs.append((tid, best))
                unmatched.discard(best)

        matched_tids = set()
        for tid, i in pairs:
            tr = self._tracks[tid]
            tr["centroid"] = cents[i]
            tr["bbox"] = boxes[i]
            tr["missed"] = 0
            tr["hits"] += 1
            matched_tids.add(tid)

        # Neue Tracks fuer uebrig gebliebene Boxen
        for i in unmatched:
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = {"centroid": cents[i], "bbox": boxes[i],
                                 "missed": 0, "hits": 1}
            matched_tids.add(tid)

        # Verpasste Tracks altern lassen / abschliessen
        for tid in list(self._tracks.keys()):
            if tid in matched_tids:
                continue
            tr = self._tracks[tid]
            tr["missed"] += 1
            if tr["missed"] > self.max_missed:
                self._finished.append(tid)
                del self._tracks[tid]

        return [{"id": tid, "bbox": self._tracks[tid]["bbox"]}
                for tid in self._tracks
                if self._tracks[tid]["missed"] == 0
                and self._tracks[tid]["hits"] >= self.min_hits]

    def pop_finished(self):
        out = self._finished
        self._finished = []
        return out
