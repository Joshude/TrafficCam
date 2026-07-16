"""Pipeline: Bewegungserkennung -> Tracking -> Speed/Laenge -> Filter -> Log."""
from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict, deque

import cv2
import numpy as np
import yaml

from .geometry import (Distortion, GroundPlane, estimate_speed, ground_point,
                       point_in_polygon, side_of_line)
from .motion import CentroidTracker, MotionDetector
from .schedule import tracking_active

COLOR = (40, 200, 80)
COLOR_CROSS = (0, 215, 255)
ZONE_COLOR = (60, 160, 255)
LINE_COLOR = (40, 80, 230)
TRAIL_COLOR = (80, 200, 255)
ANCHOR_COLOR = (255, 255, 0)      # KI-Anker (cyan)
START_COLOR = (80, 220, 80)
END_COLOR = (60, 60, 230)


class Pipeline(threading.Thread):
    def __init__(self, capture, config, storage, settings, mqtt=None):
        super().__init__(daemon=True)
        self.capture = capture
        self.config = config
        self.storage = storage
        self.settings = settings
        self.mqtt = mqtt
        self._running = True

        self._frame_lock = threading.Lock()
        self._annotated = None
        self._raw = None

        self._plane_lock = threading.Lock()
        self.plane = None
        self.trigger_line = None
        self.zone = None
        self.calib_points = None
        self.calib_world = None
        self._reload_calibration()

        # Zustand je Track-ID
        self._samples = defaultdict(lambda: deque(maxlen=400))
        self._side = {}
        self._crossed = set()
        self._best = {}                       # groesster Anblick: (area, frame, bbox)

        self.fps = 0.0
        self.last_error = None
        self.detector = None
        self.tracking_on = True
        self.tracking_reason = "aktiv"
        self._sched_checked = 0.0
        self._detection_dirty = False
        self.dusk_active = False      # kompatibel: True bei Daemmerung/Nacht
        self.detection_phase = "tag"  # tag | daemmerung | nacht
        self.hybrid = None            # KI-Anker-Worker (erweiterte Erfassung)
        self.hybrid_on = False
        self._anchors = {}            # tid -> [(ts, wx, wy, ix, iy), ...]
        self.classifier = None
        self.classify_on = False
        self._purge_checked = 0.0

    # ---- Kalibrierung -----------------------------------------------------
    def _reload_calibration(self):
        cfg = self.config.get()
        path = cfg["calibration_file"]
        plane, line = None, None
        zone = cfg.get("zone")  # Fallback aus config.yaml
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                dd = data.get("distortion")
                dist = (Distortion(dd["lambda"], dd["cx"], dd["cy"],
                                   dd["scale"]) if dd else None)
                ip, wp = data.get("image_points"), data.get("world_points")
                if ip and wp:
                    plane = GroundPlane(ip, wp, dist=dist)
                    self.calib_points = ip
                    self.calib_world = wp
                tl = data.get("trigger_line")
                if tl and len(tl) == 2:
                    line = tl
                z = data.get("zone")
                if z is not None:
                    zone = z if len(z) >= 3 else None
            except Exception as e:
                self.last_error = f"Kalibrierung ungueltig: {e}"
                with self._plane_lock:
                    self.plane, self.trigger_line, self.zone = None, None, None
                return False
        with self._plane_lock:
            self.plane, self.trigger_line, self.zone = plane, line, zone
        return True

    def reload_plane(self):
        return self._reload_calibration()

    # ---- Frame-Zugriff ------------------------------------------------------
    def get_annotated(self):
        with self._frame_lock:
            return None if self._annotated is None else self._annotated.copy()

    def get_raw(self):
        with self._frame_lock:
            return None if self._raw is None else self._raw.copy()

    # ---- Hauptschleife ------------------------------------------------------
    def run(self):
        detector, tracker, sp = self._build_detection()

        last_seq = None
        t_prev = time.monotonic()

        while self._running:
            seq, ts, frame = self.capture.read()
            if frame is None or seq == last_seq:
                time.sleep(0.005)
                continue
            last_seq = seq

            with self._frame_lock:
                self._raw = frame

            if self._detection_dirty:
                self._detection_dirty = False
                detector, tracker, sp = self._build_detection()

            now_wall = time.time()
            if now_wall - self._sched_checked > 20:
                self._sched_checked = now_wall
                self.tracking_on, self.tracking_reason = tracking_active(
                    self.settings.get())
                phase = self._detection_phase(now_wall)
                if phase != self.detection_phase:
                    self.detection_phase = phase
                    self.dusk_active = phase != "tag"
                    self._detection_dirty = True
                self._maybe_purge(now_wall)
                self._anchors = {k: v for k, v in self._anchors.items()
                                 if k in self._samples}
            if not self.tracking_on:
                paused = frame.copy()
                cv2.putText(paused, f"Tracking {self.tracking_reason}",
                            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (60, 60, 230), 2)
                with self._frame_lock:
                    self._annotated = paused
                time.sleep(0.2)
                continue

            try:
                boxes = detector.detect(frame)
            except Exception as e:
                self.last_error = f"Erkennungs-Fehler: {e}"
                boxes = []

            dets = tracker.update(boxes, frame.shape[1])

            with self._plane_lock:
                plane = self.plane
                line = self.trigger_line
                zone = self.zone

            ovl = self.settings.get()
            annotated = frame.copy()
            if ovl.get("show_mask", False):
                self._overlay_mask(annotated, detector.last_mask)
            if zone and ovl.get("show_zone", True):
                cv2.polylines(annotated, [np.array(zone, np.int32)],
                              True, ZONE_COLOR, 1)
            if line and ovl.get("show_line", True):
                cv2.line(annotated, tuple(map(int, line[0])),
                         tuple(map(int, line[1])), LINE_COLOR, 1)

            offer_tracks = []
            for det in dets:
                tid, bbox = det["id"], det["bbox"]
                gp = ground_point(bbox)
                in_zone = point_in_polygon(gp, zone)
                if in_zone:
                    offer_tracks.append((tid, list(bbox)))

                if plane is not None and in_zone:
                    wpt = plane.to_world([gp])[0]
                    if np.all(np.isfinite(wpt)):
                        self._samples[tid].append(
                            (ts, float(wpt[0]), float(wpt[1]),
                             float(gp[0]), float(gp[1])))

                if line:
                    s = side_of_line(gp, line)
                    prev = self._side.get(tid)
                    if (prev is not None and prev != 0 and s != 0
                            and (s > 0) != (prev > 0)):
                        self._crossed.add(tid)
                    self._side[tid] = s

                # Frame mit groesster Box als Snapshot-Kandidat merken
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                if in_zone and (tid not in self._best
                                or area > self._best[tid][0]):
                    self._best[tid] = (area, frame.copy(), list(bbox))

                if ovl.get("show_trail", True):
                    self._draw_trail(annotated,
                                     list(self._samples.get(tid, [])))
                    for a in self._anchors.get(tid, []):
                        cv2.circle(annotated, (int(a[3]), int(a[4])),
                                   4, ANCHOR_COLOR, -1)
                if ovl.get("show_boxes", True):
                    self._draw(annotated, tid, bbox, tid in self._crossed)

            if self.hybrid_on and self.hybrid is not None:
                for a_tid, a_ts, a_box in self.hybrid.collect():
                    a_gp = ground_point(a_box)
                    if plane is None or not point_in_polygon(a_gp, zone):
                        continue
                    a_w = plane.to_world([a_gp])[0]
                    if not np.all(np.isfinite(a_w)):
                        continue
                    # Plausibilitaet: Anker muss in der Naehe der MOG2-Spur
                    # desselben Tracks liegen - sonst hat der Worker ein
                    # fremdes (z.B. geparktes) Fahrzeug gematcht
                    trk = self._samples.get(a_tid)
                    if trk:
                        near = min(trk, key=lambda s: abs(s[0] - a_ts))
                        d = math.hypot(a_w[0] - near[1], a_w[1] - near[2])
                        if d > 3.0:
                            continue
                    lst = self._anchors.setdefault(a_tid, [])
                    lst.append((a_ts, float(a_w[0]), float(a_w[1]),
                                float(a_gp[0]), float(a_gp[1])))
                    if len(lst) > 40:
                        del lst[0]
                if (offer_tracks and zone and plane is not None
                        and self.hybrid.ready_for_frame()):
                    from .hybrid import zone_rect
                    rect = zone_rect(frame.shape, zone)
                    self.hybrid.offer(ts, frame, offer_tracks, rect)

            for tid in tracker.pop_finished():
                self._finalize(tid, sp, line)

            now = time.monotonic()
            dt = now - t_prev
            t_prev = now
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
            cv2.putText(annotated, f"{self.fps:4.1f} FPS", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            with self._frame_lock:
                self._annotated = annotated

    def _detection_phase(self, t):
        """Aktuelle Phase: "tag", "daemmerung" oder "nacht".

        Daemmerung: ab (Sonnenuntergang - vor_min) bzw. bis
        (Sonnenaufgang + nach_min). Nacht (falls aktiviert): sobald der
        Sonnenuntergang laenger her ist als nach_sonnenuntergang_min bzw.
        der Sonnenaufgang weiter entfernt als vor_sonnenaufgang_min -
        dann ist das Bild im IR-Modus und Scheinwerferkegel dominieren.
        Ohne Nacht-Profil deckt das Daemmerungs-Profil wie bisher die
        gesamte Nacht ab.
        """
        cfg = self.config.get()
        dd = cfg.get("motion_dusk", {})
        nn = cfg.get("motion_nacht", {})
        if not dd.get("enabled") and not nn.get("enabled"):
            return "tag"
        s = self.settings.get()
        try:
            from .schedule import sun_epochs
            rise, sset = sun_epochs(float(s.get("lat", 0)),
                                    float(s.get("lon", 0)), t)
        except Exception:
            return "tag"
        after = float(dd.get("nach_sonnenaufgang_min", 60)) * 60.0
        before = float(dd.get("vor_sonnenuntergang_min", 60)) * 60.0
        if rise + after <= t <= sset - before:
            return "tag"
        if nn.get("enabled"):
            n_after = float(nn.get("nach_sonnenuntergang_min", 45)) * 60.0
            n_before = float(nn.get("vor_sonnenaufgang_min", 45)) * 60.0
            if t > sset + n_after or t < rise - n_before:
                return "nacht"
        return "daemmerung" if dd.get("enabled") else "tag"

    def _build_detection(self):
        """Erzeugt Detektor+Tracker aus der aktuellen Config
        (inkl. Daemmerungs- bzw. Nacht-Profil, falls gerade aktiv)."""
        cfg = self.config.get()
        m = dict(cfg["motion"])
        prof = None
        if self.detection_phase == "daemmerung":
            prof = cfg.get("motion_dusk", {})
        elif self.detection_phase == "nacht":
            prof = cfg.get("motion_nacht", {})
        if prof:
            for k in ("var_threshold", "shadow_threshold",
                      "tighten_min_fill", "min_area", "merge_gap"):
                if prof.get(k) is not None:
                    m[k] = prof[k]
        sp = cfg["speed"]
        detector = self.detector = MotionDetector(
            proc_width=m["proc_width"],
            min_area=m["min_area"],
            merge_gap=m["merge_gap"],
            var_threshold=m.get("var_threshold", 32),
            shadow_threshold=m.get("shadow_threshold", 0.3),
            tighten_min_fill=m.get("tighten_min_fill", 0.15))
        tracker = CentroidTracker(max_dist_frac=m["max_dist_frac"],
                                  max_missed=m["max_missed"],
                                  min_hits=m["min_hits"])
        det_cfg = cfg.get("detector", {})
        if det_cfg.get("erfassung", "einfach") == "erweitert":
            if self.hybrid is None:
                from .hybrid import HybridAnchorWorker
                self.hybrid = HybridAnchorWorker(
                    model=det_cfg.get("model", "yolo11n.pt"),
                    conf=det_cfg.get("conf", 0.35),
                    imgsz=det_cfg.get("hybrid_imgsz", 320),
                    min_interval=det_cfg.get("hybrid_intervall_s", 0.15))
                self.hybrid.start()
            self.hybrid_on = True
        else:
            self.hybrid_on = False
        if det_cfg.get("classify_snapshots"):
            if self.classifier is None:
                from .classify import SnapshotClassifier
                self.classifier = SnapshotClassifier(
                    self.storage,
                    model=det_cfg.get("model", "yolo11n.pt"),
                    conf=det_cfg.get("conf", 0.35),
                    imgsz=det_cfg.get("imgsz", 640))
                self.classifier.start()
            self.classify_on = True
        else:
            self.classify_on = False
        return detector, tracker, sp

    def reload_detection(self):
        """Von der Web-UI aufgerufen: Erkennung ohne Neustart neu aufbauen."""
        self._detection_dirty = True

    def ensure_classifier(self):
        """Klassifizierer passend zum Config-Flag starten/stoppen."""
        det = self.config.get().get("detector", {})
        want = bool(det.get("classify_snapshots"))
        if want and self.classifier is None:
            from .classify import SnapshotClassifier
            self.classifier = SnapshotClassifier(
                self.storage,
                model=det.get("model", "yolo11n.pt"),
                conf=det.get("conf", 0.35),
                imgsz=det.get("imgsz", 640))
            self.classifier.start()
        elif not want and self.classifier is not None:
            self.classifier = None   # Daemon-Thread laeuft leer aus

    @staticmethod
    def _overlay_mask(img, mask):
        """Faerbt erkannte Bewegungspixel rot ein (Diagnose-Ansicht)."""
        if mask is None:
            return
        m = cv2.resize(mask, (img.shape[1], img.shape[0]),
                       interpolation=cv2.INTER_NEAREST)
        sel = m > 0
        if sel.any():
            img[sel] = (img[sel] * 0.35
                        + np.array([40, 40, 230]) * 0.65).astype(np.uint8)

    @staticmethod
    def _draw_trail(img, samples, with_markers=False):
        """Zeichnet die Mess-Spur (Bodenpunkte) eines Tracks."""
        pts = [(int(s[3]), int(s[4])) for s in samples]
        if len(pts) < 2:
            return
        cv2.polylines(img, [np.array(pts, np.int32)], False, TRAIL_COLOR, 1)
        for pt in pts:
            cv2.circle(img, pt, 3, TRAIL_COLOR, -1)
        if with_markers:
            cv2.circle(img, pts[0], 5, START_COLOR, -1)
            cv2.circle(img, pts[0], 5, (255, 255, 255), 1)
            cv2.circle(img, pts[-1], 5, END_COLOR, -1)
            cv2.circle(img, pts[-1], 5, (255, 255, 255), 1)

    def _draw(self, img, tid, bbox, crossed):
        x1, y1, x2, y2 = [int(v) for v in bbox]
        color = COLOR_CROSS if crossed else COLOR
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)
        cv2.putText(img, f"#{tid}", (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

    def _maybe_purge(self, now):
        """Loescht stuendlich Messungen aelter als die Aufbewahrungsfrist."""
        if now - self._purge_checked < 3600:
            return 0
        self._purge_checked = now
        days = float(self.settings.get().get("aufbewahrung_tage", 0) or 0)
        if days <= 0:
            return 0
        try:
            n = self.storage.delete_where(ts_to=now - days * 86400.0)
            if n:
                print(f"[purge] {n} Messungen aelter als {days:.0f} Tage "
                      "entfernt", flush=True)
            return n
        except Exception as e:
            self.last_error = f"Auto-Purge fehlgeschlagen: {e}"
            return 0

    def _finalize(self, tid, sp, line):
        samples = list(self._samples.pop(tid, []))
        anchors = list(self._anchors.pop(tid, []))
        best = self._best.pop(tid, None)
        self._side.pop(tid, None)
        crossed = tid in self._crossed
        self._crossed.discard(tid)

        if not samples:
            return
        if line is not None and not crossed:
            return

        result = None
        if self.hybrid_on and len(anchors) >= 3:
            # KI-Anker: wenige, aber beleuchtungsunabhaengige Punkte -
            # niedrigere Mindestanzahl, gleiche uebrige Schwellen
            result = estimate_speed(anchors, 3,
                                    min(sp["min_time"], 0.3),
                                    sp["min_disp"], sp["max_kmh"])
            if result and (result.get("residual_m", 0)
                           > sp.get("max_residual_m", 0.6)):
                result = None      # zerrissene Anker -> lieber MOG2-Fit
            if result:
                result["erfassung"] = "erweitert"
        if result is None:
            result = estimate_speed(samples, sp["min_samples"],
                                    sp["min_time"], sp["min_disp"],
                                    sp["max_kmh"])
            if result:
                result["erfassung"] = "einfach"
        if not result:
            return

        if result.get("residual_m", 0) > sp.get("max_residual_m", 0.6):
            return          # zerrissener Pfad (Track-Verwechslung) - verwerfen
        f = self.settings.get()
        if not (f["min_kmh"] <= result["speed_kmh"] <= f["max_kmh"]):
            return

        punkte = {
            "samples": [[round(s[0] - samples[0][0], 3), round(s[1], 2),
                         round(s[2], 2), round(s[3], 1), round(s[4], 1)]
                        for s in samples[:120]],
            "anchors": [[round(a[0] - samples[0][0], 3), round(a[1], 2),
                         round(a[2], 2), round(a[3], 1), round(a[4], 1)]
                        for a in anchors[:40]],
        } if samples else None

        snap_frame, raw_frame, bbox = None, None, None
        if best is not None:
            raw_frame = best[1]
            bbox = best[2]
            snap_frame = self._annotate_snapshot(raw_frame, bbox, result,
                                                 samples, anchors)
        ts, event_id = self.storage.save_event(result, snap_frame,
                                               raw_frame, bbox,
                                               punkte=punkte)
        if (self.classify_on and self.classifier is not None
                and raw_frame is not None and bbox is not None):
            self.classifier.submit(event_id, raw_frame, bbox)
        if self.mqtt is not None:
            self.mqtt.publish_event(result, self.storage.stats(), ts)

    @classmethod
    def _annotate_snapshot(cls, frame, bbox, result, samples=None,
                           anchors=None):
        img = frame.copy()
        if anchors:
            for a in anchors:
                cv2.circle(img, (int(a[3]), int(a[4])), 5, ANCHOR_COLOR, -1)
        if samples:
            cls._draw_trail(img, samples, with_markers=True)
            pts = [(int(s[3]), int(s[4])) for s in samples]
            if len(pts) >= 2:
                mid = pts[len(pts) // 2]
                info = f"{result['distance_m']} m / {result['duration_s']} s"
                pos = (mid[0] + 8, min(mid[1] + 20, img.shape[0] - 8))
                cv2.putText(img, info, pos, cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 0, 0), 3)
                cv2.putText(img, info, pos, cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, TRAIL_COLOR, 1)
        x1, y1, x2, y2 = [int(v) for v in bbox]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 215, 255), 3)
        # Richtungs-Pfeil unter der Box
        ymid = min(y2 + 24, img.shape[0] - 10)
        if result["direction"] == "links->rechts":
            cv2.arrowedLine(img, (x1, ymid), (x2, ymid), (0, 215, 255), 3,
                            tipLength=0.06)
        else:
            cv2.arrowedLine(img, (x2, ymid), (x1, ymid), (0, 215, 255), 3,
                            tipLength=0.06)
        label = f"{result['speed_kmh']:.1f} km/h"
        ty = max(y1 - 12, 28)
        cv2.putText(img, label, (x1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (0, 0, 0), 5)
        cv2.putText(img, label, (x1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (0, 215, 255), 2)
        return img

    def stop(self):
        self._running = False
