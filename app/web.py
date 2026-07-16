"""Flask-UI: Live-Stream, Filter-Einstellungen, Ereignisse mit Snapshots."""
from __future__ import annotations

import os
import time

import cv2
import yaml
import numpy as np
from flask import (Flask, Response, jsonify, render_template_string,
                   request, send_from_directory)


def _poly_area(points):
    """Shoelace-Flaeche der konvexen Huelle - ~0 bei kollinearen Punkten."""
    pts = np.array(points, dtype=np.float64)
    hull = cv2.convexHull(pts.astype(np.float32))
    return float(cv2.contourArea(hull))


def create_app(pipeline, storage, config, settings):
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            INDEX_HTML_EN if _lang() == "en" else INDEX_HTML)

    @app.route("/stream.mjpg")
    def stream():
        q = config.get()["web"]["stream_quality"]

        def gen():
            while True:
                frame = pipeline.get_annotated()
                if frame is None:
                    time.sleep(0.1)
                    continue
                ok, buf = cv2.imencode(".jpg", frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, q])
                if not ok:
                    continue
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + buf.tobytes() + b"\r\n")
                time.sleep(0.04)

        return Response(gen(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/snapshot.jpg")
    def snapshot():
        frame = pipeline.get_raw()
        if frame is None:
            return Response(status=503)
        ok, buf = cv2.imencode(".jpg", frame)
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/snap/<path:name>")
    def snap(name):
        return send_from_directory(
            config.get()["storage"]["snapshot_dir"], name)

    @app.route("/calib_grid.jpg")
    def calib_grid():
        frame = pipeline.get_raw()
        plane = pipeline.plane
        if frame is None or plane is None:
            img = np.zeros((240, 640, 3), np.uint8)
            cv2.putText(img, "keine Kalibrierung / kein Bild", (30, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
            ok, buf = cv2.imencode(".jpg", img)
            return Response(buf.tobytes(), mimetype="image/jpeg")

        img = frame.copy()
        try:
            Hi = np.linalg.inv(plane.H)
            h, w_ = img.shape[:2]
            if pipeline.calib_world:
                wparr = np.array(pipeline.calib_world, dtype=float)
                cxw, cyw = wparr.mean(axis=0)
                spanx = max(float(np.ptp(wparr[:, 0])), 2.0)
                spany = max(float(np.ptp(wparr[:, 1])), 2.0)
                xmin, xmax = cxw - spanx, cxw + spanx
                ymin, ymax = cyw - spany, cyw + spany
            else:
                corners = plane.to_world([[0, h * 0.4], [w_, h * 0.4],
                                          [w_, h], [0, h]])
                xmin, ymin = corners.min(axis=0) - 1
                xmax, ymax = corners.max(axis=0) + 1
            xmin, xmax = max(xmin, -40), min(xmax, 40)
            ymin, ymax = max(ymin, -40), min(ymax, 40)

            def to_img(pts):
                a = np.array(pts, np.float32).reshape(-1, 1, 2)
                return cv2.perspectiveTransform(a, Hi).reshape(-1, 2)

            import math

            def wline(a, b, major):
                ts = np.linspace(0.0, 1.0, 33)
                ws = np.stack([a[0] + (b[0] - a[0]) * ts,
                               a[1] + (b[1] - a[1]) * ts], axis=1)
                ps = to_img(ws)
                if plane.dist is not None:
                    ps = plane.dist.redistort(ps)
                for k in range(len(ps) - 1):
                    a, b = ps[k], ps[k + 1]
                    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
                        continue
                    a = np.clip(a, -20000, 20000).astype(int)
                    b = np.clip(b, -20000, 20000).astype(int)
                    cv2.line(img, tuple(a), tuple(b),
                             (80, 220, 80), 2 if major else 1)

            for x in range(math.ceil(xmin), math.floor(xmax) + 1):
                wline([x, ymin], [x, ymax], x % 5 == 0)
            for y in range(math.ceil(ymin), math.floor(ymax) + 1):
                wline([xmin, y], [xmax, y], y % 5 == 0)
            if pipeline.calib_points:
                for i, (px, py) in enumerate(pipeline.calib_points):
                    cv2.circle(img, (int(px), int(py)), 7, (0, 0, 255), -1)
                    cv2.putText(img, str(i + 1), (int(px) + 10, int(py) - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(img, "1-m-Raster (dick = 5 m)", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 220, 80), 2)
        except Exception as e:
            cv2.putText(img, f"Fehler: {e}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        ok, buf = cv2.imencode(".jpg", img)
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/api/events")
    def events():
        return jsonify(storage.recent(int(request.args.get("limit", 50))))

    @app.route("/api/events/<int:event_id>", methods=["DELETE"])
    def delete_event(event_id):
        return jsonify({"ok": storage.delete(event_id)})

    @app.route("/api/events", methods=["DELETE"])
    def delete_all_events():
        storage.delete_all()
        return jsonify({"ok": True})

    def _lang():
        return settings.get().get("sprache", "de")

    def _tr_status(s):
        if _lang() != "en":
            return s
        from . import i18n
        if s.startswith("aktiv ("):        # z.B. "aktiv (81.2 ms)"
            return s.replace("aktiv", "active", 1)
        return i18n.status_en(s)

    def _hybrid_status():
        if not getattr(pipeline, "hybrid_on", False):
            return "aus"
        hw = getattr(pipeline, "hybrid", None)
        if hw is None or hw.available is None:
            return "startet"
        if hw.available is False:
            return "ultralytics fehlt"
        ms = getattr(hw, "inference_ms", None)
        return f"aktiv ({ms} ms)" if ms else "aktiv"

    @app.route("/api/stats")
    def stats():
        return jsonify({
            "fps": round(pipeline.fps, 1),
            "connected": getattr(pipeline.capture, "connected", False),
            "calibrated": pipeline.plane is not None,
            "tracking_on": getattr(pipeline, "tracking_on", True),
            "tracking_reason": _tr_status(
                getattr(pipeline, "tracking_reason", "")),
            "dusk_profile": getattr(pipeline, "dusk_active", False),
            "phase": getattr(pipeline, "detection_phase", "tag"),
            "hybrid": _tr_status(_hybrid_status()),
            "has_line": pipeline.trigger_line is not None,
            "has_zone": pipeline.zone is not None,
            "error": pipeline.last_error,
            "mqtt": (getattr(pipeline.mqtt, "error", None) is None
                     and pipeline.mqtt is not None)
                    if pipeline.mqtt is not None else None,
            "totals": storage.stats(),
        })

    @app.route("/api/settings", methods=["GET", "POST"])
    def api_settings():
        if request.method == "POST":
            try:
                return jsonify({"ok": True,
                                "settings": settings.update(
                                    request.get_json(force=True))})
            except (TypeError, ValueError) as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify(settings.get())

    def _parse_filters(args):
        import time as _t
        f = {}
        for k in ("min_kmh", "max_kmh"):
            v = args.get(k)
            if v not in (None, ""):
                try:
                    f[k] = float(str(v).replace(",", "."))
                except ValueError:
                    pass
        r = args.get("richtung")
        if r:
            f["richtung"] = r
        k = args.get("klasse")
        if k:
            f["klasse"] = k
        for k, key, off in (("from", "ts_from", 0), ("to", "ts_to", 86400)):
            d = args.get(k)
            if d:
                try:
                    f[key] = _t.mktime(_t.strptime(d, "%Y-%m-%d")) + off
                except ValueError:
                    pass
        return f

    def _kpi_from(speeds, limit):
        speeds = sorted(speeds)
        n = len(speeds)

        def pct(p):
            if not n:
                return 0.0
            i = p * (n - 1)
            lo = int(i)
            hi = min(lo + 1, n - 1)
            return round(speeds[lo] + (speeds[hi] - speeds[lo]) * (i - lo), 1)

        return {"anzahl": n,
                "avg": round(sum(speeds) / n, 1) if n else 0,
                "median": pct(0.50), "v85": pct(0.85),
                "max": round(speeds[-1], 1) if n else 0,
                "limit": limit,
                "ueber_limit_pct": round(
                    100.0 * sum(1 for s in speeds if s > limit) / n, 1)
                if n else 0.0}

    def _aggregate_charts(rows):
        """rows: Liste (ts, speed, richtung) -> Diagrammdaten."""
        import time as _t
        speeds = sorted(r[1] for r in rows)
        n = len(speeds)
        top = max(60, (int(speeds[-1] // 5) + 1) * 5) if n else 60
        bins = list(range(0, top, 5))
        hist = [0] * len(bins)
        for s in speeds:
            hist[min(int(s // 5), len(bins) - 1)] += 1
        hour_n = [0] * 24
        hour_sum = [0.0] * 24
        for ts, s, _ in rows:
            h = _t.localtime(ts).tm_hour
            hour_n[h] += 1
            hour_sum[h] += s
        hour_avg = [round(hour_sum[h] / hour_n[h], 1) if hour_n[h] else 0
                    for h in range(24)]
        days, day_n, day_sum = [], [], []
        now = _t.time()
        for k in range(13, -1, -1):
            d0 = _t.localtime(now - k * 86400)
            days.append(_t.strftime("%d.%m.", d0))
            day_n.append(0)
            day_sum.append(0.0)
        for ts, s, _ in rows:
            k = int((_t.mktime(_t.localtime(now)[:3] + (0, 0, 0) + _t.localtime(now)[6:])
                     - _t.mktime(_t.localtime(ts)[:3] + (0, 0, 0) + _t.localtime(ts)[6:])) // 86400)
            idx = 13 - k
            if 0 <= idx < 14:
                day_n[idx] += 1
                day_sum[idx] += s
        day_avg = [round(day_sum[i] / day_n[i], 1) if day_n[i] else 0
                   for i in range(14)]
        rich = {}
        for ts, s, r in rows:
            e = rich.setdefault(r or "?", {"n": 0, "sum": 0.0, "vals": []})
            e["n"] += 1
            e["sum"] += s
            e["vals"].append(s)

        def _median(vals):
            v = sorted(vals)
            m = len(v) // 2
            return round((v[m] if len(v) % 2 else (v[m-1]+v[m])/2), 1)
        richtung = [{"richtung": k, "n": v["n"],
                     "avg": round(v["sum"] / v["n"], 1),
                     "median": _median(v["vals"])}
                    for k, v in rich.items()]
        return {"bins": bins, "hist": hist, "hour_n": hour_n,
                "hour_avg": hour_avg, "days": days, "day_n": day_n,
                "day_avg": day_avg, "richtung": richtung}

    DETECTION_FIELDS = {
        "motion": {"var_threshold": (float, 4, 200),
                   "shadow_threshold": (float, 0.05, 0.9),
                   "tighten_min_fill": (float, 0.0, 0.9),
                   "min_area": (int, 20, 20000),
                   "merge_gap": (int, 0, 200)},
        "speed": {"max_residual_m": (float, 0.05, 5.0)},
    }

    @app.route("/api/detection", methods=["GET", "POST"])
    def api_detection():
        if request.method == "GET":
            cfg = config.get()
            out = {}
            for section, fields in DETECTION_FIELDS.items():
                for k in fields:
                    out[k] = cfg[section].get(k)
            out["classify_snapshots"] = bool(
                cfg.get("detector", {}).get("classify_snapshots"))
            out["dusk_enabled"] = bool(
                cfg.get("motion_dusk", {}).get("enabled"))
            out["nacht_enabled"] = bool(
                cfg.get("motion_nacht", {}).get("enabled"))
            out["erfassung"] = cfg.get("detector", {}).get(
                "erfassung", "einfach")
            return jsonify(out)
        data = request.get_json(force=True)
        updates = {}
        if "classify_snapshots" in data:
            updates["detector"] = {
                "classify_snapshots": bool(data["classify_snapshots"])}
        if "dusk_enabled" in data:
            updates["motion_dusk"] = {"enabled": bool(data["dusk_enabled"])}
        if "nacht_enabled" in data:
            updates["motion_nacht"] = {"enabled": bool(data["nacht_enabled"])}
        if "erfassung" in data:
            if data["erfassung"] not in ("einfach", "erweitert"):
                return jsonify({"ok": False,
                                "error": "erfassung: einfach|erweitert"}), 400
            updates.setdefault("detector", {})["erfassung"] = \
                data["erfassung"]
        for section, fields in DETECTION_FIELDS.items():
            vals = {}
            for k, (typ, lo, hi) in fields.items():
                if k not in data or data[k] in (None, ""):
                    continue
                try:
                    v = typ(float(str(data[k]).replace(",", ".")))
                except (TypeError, ValueError):
                    return jsonify({"ok": False,
                                    "error": f"{k}: ungueltiger Wert"}), 400
                if not (lo <= v <= hi):
                    return jsonify({"ok": False, "error":
                        f"{k}: erlaubt {lo}..{hi}"}), 400
                vals[k] = v
            if vals:
                updates[section] = vals
        if not updates:
            return jsonify({"ok": False, "error": "keine Werte"}), 400
        config.update_values(updates)
        pipeline.reload_detection()
        if hasattr(pipeline, "ensure_classifier"):
            pipeline.ensure_classifier()
        return jsonify({"ok": True})

    @app.route("/einstellungen")
    def einstellungen():
        return render_template_string(
            SETTINGS_PAGE_HTML_EN if _lang() == "en" else SETTINGS_PAGE_HTML)

    from .benchmark import BenchmarkRunner
    bench = BenchmarkRunner(
        model=config.get().get("detector", {}).get("model", "yolo11n.pt"))

    @app.route("/api/benchmark", methods=["GET", "POST"])
    def api_benchmark():
        if request.method == "GET":
            st = bench.status()
            if _lang() == "en":
                from . import i18n
                st = i18n.bench_en(st)
            return jsonify(st)
        frame = pipeline.get_raw()
        if frame is None:
            return jsonify({"ok": False,
                            "error": "kein Kamerabild verf\u00fcgbar"}), 400
        started = bench.start(frame, getattr(pipeline, "zone", None))
        if not started:
            return jsonify({"ok": False, "error": "l\u00e4uft bereits"}), 409
        return jsonify({"ok": True})

    @app.route("/system")
    def system_page():
        return render_template_string(
            SYSTEM_HTML_EN if _lang() == "en" else SYSTEM_HTML)

    @app.route("/api/system")
    def api_system():
        info = storage.info()
        info["aufbewahrung_tage"] = settings.get().get(
            "aufbewahrung_tage", 0)
        return jsonify(info)

    @app.route("/messungen")
    def messungen():
        return render_template_string(
            EVENTS_HTML_EN if _lang() == "en" else EVENTS_HTML)

    @app.route("/api/events/query", methods=["GET", "DELETE"])
    def events_query():
        filters = _parse_filters(request.args)
        if request.method == "DELETE":
            return jsonify({"ok": True,
                            "deleted": storage.delete_where(**filters)})
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        total, rows, light = storage.query_events(
            limit=limit, offset=offset, **filters)
        kpi = _kpi_from([r[1] for r in light],
                        settings.get().get("tempolimit_kmh", 30.0))
        return jsonify({"total": total, "events": rows, "kpi": kpi,
                        "charts": _aggregate_charts(light)})

    @app.route("/statistik")
    def statistik():
        return render_template_string(
            STATS_HTML_EN if _lang() == "en" else STATS_HTML)

    @app.route("/api/statistics")
    def api_statistics():
        import time as _t
        rng = request.args.get("range", "7d")
        since = {"24h": 86400, "7d": 7 * 86400,
                 "30d": 30 * 86400}.get(rng, 0)
        rows = storage.speeds_since(_t.time() - since if since else 0)
        limit = settings.get().get("tempolimit_kmh", 30.0)
        kpi = _kpi_from([r[1] for r in rows], limit)
        agg = _aggregate_charts(rows)
        return jsonify({"kpi": kpi, **agg})

    @app.route("/referenzen")
    def referenzen():
        return render_template_string(
            REFINE_HTML_EN if _lang() == "en" else REFINE_HTML)

    @app.route("/api/refine", methods=["POST"])
    def api_refine():
        from .refine import refine_points
        from .geometry import Distortion
        data = request.get_json(force=True)
        ip = data.get("image_points")
        wp = data.get("world_points")
        fixed = data.get("fixed")
        refs = data.get("references") or []
        dd = data.get("distortion")
        if not ip or not wp or len(ip) != len(wp) or len(ip) < 4:
            return jsonify({"ok": False, "error":
                "keine gueltige Basis-Kalibrierung geladen"}), 400
        if not fixed or len(fixed) != len(ip):
            return jsonify({"ok": False, "error":
                "fixed-Maske passt nicht zur Punktanzahl"}), 400
        dist = (Distortion(dd["lambda"], dd["cx"], dd["cy"], dd["scale"])
                if dd else None)
        try:
            new_wp, report, warn = refine_points(ip, wp, fixed, refs, dist=dist)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "world_points": new_wp,
                        "report": report, "warn": warn})

    @app.route("/calibrate")
    def calibrate():
        return render_template_string(
            CALIB_HTML_EN if _lang() == "en" else CALIB_HTML)

    @app.route("/motion_mask.jpg")
    def motion_mask():
        det = getattr(pipeline, "detector", None)
        mask = getattr(det, "last_mask", None) if det else None
        frame = pipeline.get_raw()
        if mask is None:
            img = np.zeros((240, 640, 3), np.uint8)
            cv2.putText(img, "noch keine Maske (Erkennung laeuft nicht?)",
                        (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 0, 255), 2)
        else:
            if frame is not None:
                mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]),
                                  interpolation=cv2.INTER_NEAREST)
                img = cv2.addWeighted(
                    frame, 0.35,
                    cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), 0.65, 0)
            else:
                img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            cv2.putText(img, "Bewegungsmaske (weiss = erkannte Bewegung)",
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (80, 220, 80), 1)
        ok, buf = cv2.imencode(".jpg", img)
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/undistort_preview.jpg")
    def undistort_preview():
        from .geometry import Distortion
        frame = pipeline.get_raw()
        path = config.get()["calibration_file"]
        dd = None
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    dd = (yaml.safe_load(f) or {}).get("distortion")
            except Exception:
                dd = None
        if frame is None or not dd:
            img = np.zeros((240, 640, 3), np.uint8)
            cv2.putText(img, "keine Entzerrung / kein Bild", (30, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
            ok, buf = cv2.imencode(".jpg", img)
            return Response(buf.tobytes(), mimetype="image/jpeg")
        dist = Distortion(dd["lambda"], dd["cx"], dd["cy"], dd["scale"])
        h, w_ = frame.shape[:2]
        xs, ys = np.meshgrid(np.arange(w_, dtype=np.float64),
                             np.arange(h, dtype=np.float64))
        pts = np.stack([xs.ravel(), ys.ravel()], axis=1)
        src = dist.redistort(pts)          # Ziel(entzerrt) -> Quelle(verzerrt)
        mapx = np.nan_to_num(src[:, 0], nan=-1).reshape(h, w_).astype(np.float32)
        mapy = np.nan_to_num(src[:, 1], nan=-1).reshape(h, w_).astype(np.float32)
        img = cv2.remap(frame, mapx, mapy, cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT)
        cv2.putText(img, "entzerrte Vorschau - gerade Kanten muessen gerade sein",
                    (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 80), 1)
        ok, buf = cv2.imencode(".jpg", img)
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/api/distortion", methods=["POST"])
    def api_distortion():
        from .geometry import estimate_lambda
        data = request.get_json(force=True)
        path = config.get()["calibration_file"]
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}

        if data.get("clear"):
            existing.pop("distortion", None)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(existing, f)
            pipeline.reload_plane()
            return jsonify({"ok": True, "cleared": True})

        lines = [l for l in (data.get("lines") or []) if len(l) >= 4]
        if not lines:
            return jsonify({"ok": False, "error":
                "mind. eine Linie mit >= 4 Punkten noetig"}), 400
        width = float(data.get("width") or 0)
        height = float(data.get("height") or 0)
        if width < 10 or height < 10:
            return jsonify({"ok": False, "error": "Bildgroesse fehlt"}), 400
        import math as _m
        cx, cy = width / 2.0, height / 2.0
        scale = _m.hypot(width, height) / 2.0
        lam, c0, c1 = estimate_lambda(lines, cx, cy, scale)
        existing["distortion"] = {"lambda": round(lam, 6), "cx": cx,
                                  "cy": cy, "scale": scale}
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f)
        pipeline.reload_plane()
        improvement = (1 - c1 / c0) * 100 if c0 > 1e-9 else 0.0
        hint = ""
        if abs(lam) > 1.45:
            hint = (" | Achtung: Wert am Suchrand - vermutlich ist eine der "
                    "Linien real nicht gerade; Vorschau pruefen")
        return jsonify({"ok": True, "lambda": round(lam, 4),
                        "verbesserung": round(improvement, 1), "hint": hint})

    @app.route("/api/calibration", methods=["GET"])
    def get_calibration():
        path = config.get()["calibration_file"]
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                data = {}
        return jsonify(data)

    @app.route("/api/calibration", methods=["POST"])
    def save_calibration():
        data = request.get_json(force=True)
        ip = data.get("image_points")
        wp = data.get("world_points")
        tl = data.get("trigger_line")

        path = config.get()["calibration_file"]
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}

        if ip is not None or wp is not None:
            if not ip or not wp or len(ip) != len(wp) or len(ip) < 4:
                return jsonify({"ok": False,
                                "error": "Mind. 4 passende Punktepaare noetig"}), 400
            if _poly_area(wp) < 1.0 or _poly_area(ip) < 400.0:
                return jsonify({"ok": False, "error":
                    "Punkte liegen (fast) auf einer Linie - sie muessen eine "
                    "Flaeche aufspannen (z.B. beide Fahrbahnraender)"}), 400
            warn = ""
            if _poly_area(wp) < 15.0:
                warn = (" | Achtung: Punkte spannen nur ~%.0f m^2 auf - "
                        "fuer verlaessliche Messung weiter auseinander "
                        "setzen (beide Fahrbahnraender)" % _poly_area(wp))
            existing["image_points"] = ip
            existing["world_points"] = wp
        if tl is not None:
            if len(tl) != 2:
                return jsonify({"ok": False,
                                "error": "Messlinie braucht genau 2 Punkte"}), 400
            existing["trigger_line"] = tl
        z = data.get("zone")
        if z is not None:
            if len(z) == 0:
                existing.pop("zone", None)
            elif len(z) < 3:
                return jsonify({"ok": False,
                                "error": "Messbereich braucht mind. 3 Punkte"}), 400
            else:
                existing["zone"] = z

        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f)
        pipeline.reload_plane()
        return jsonify({"ok": True, "warn": locals().get("warn", "")})

    return app


BASE_CSS = """
 :root{--bg:#0b0d12;--card:#141824;--card2:#1a2030;--line:#232a3d;
  --txt:#e8eaf2;--mut:#8b93ab;--acc:#4f8ef7;--ok:#3ddc84;--warn:#ffb454;
  --bad:#ff6b6b;--r:14px}
 *{box-sizing:border-box}
 body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:0;
  background:var(--bg);color:var(--txt)}
 header{padding:12px 18px;display:flex;gap:8px 16px;align-items:center;
  flex-wrap:wrap;border-bottom:1px solid var(--line);position:sticky;top:0;
  background:var(--bg);z-index:5}
 header h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.3px}
 header nav{display:flex;gap:4px 14px;flex-wrap:wrap;align-items:center;
  font-size:14px}
 header nav a{padding:4px 2px;white-space:nowrap}
 header nav a.cur{color:var(--txt);font-weight:600;
  border-bottom:2px solid var(--acc)}
 .subnav{padding:10px 18px 0;font-size:14px;display:flex;gap:18px}
 .subnav a.cur{color:var(--txt);font-weight:600;
  border-bottom:2px solid var(--acc);padding-bottom:4px}
 body{overflow-x:hidden}
 a{color:var(--acc);text-decoration:none}
 .chip{padding:4px 12px;border-radius:99px;font-size:12px;background:var(--card2);
  border:1px solid var(--line);display:inline-flex;gap:6px;align-items:center}
 .dot{width:8px;height:8px;border-radius:50%;background:var(--bad)}
 .dot.on{background:var(--ok)}
 .wrap{display:grid;grid-template-columns:minmax(340px,1.4fr) minmax(300px,1fr);
  gap:18px;padding:18px;max-width:1500px;margin:0 auto}
 @media(max-width:900px){.wrap{grid-template-columns:1fr}}
 .card{background:var(--card);border:1px solid var(--line);
  border-radius:var(--r);padding:16px}
 .card h3{margin:0 0 12px;font-size:14px;font-weight:600;color:var(--mut);
  text-transform:uppercase;letter-spacing:.8px}
 img.live{width:100%;border-radius:10px;display:block}
 button{background:var(--acc);border:0;color:#fff;font-weight:600;
  padding:9px 16px;border-radius:9px;cursor:pointer;font-size:14px}
 button:hover{filter:brightness(1.12)}
 input[type=number],input[type=text]{background:var(--bg);color:var(--txt);
  border:1px solid var(--line);border-radius:8px;padding:8px 10px;width:100%;font-size:14px}
 label{font-size:12px;color:var(--mut);display:block;margin-bottom:4px}
"""

INDEX_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TrafficCam</title><style>""" + BASE_CSS + """
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:18px}
 .kpi{background:var(--card2);border:1px solid var(--line);border-radius:10px;
  padding:10px 12px}
 .kpi b{font-size:22px;display:block}
 .kpi span{font-size:11px;color:var(--mut)}
 .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;align-items:end}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{color:var(--mut);font-weight:500;text-align:left}
 th,td{padding:8px 8px;border-bottom:1px solid var(--line)}
 td img{height:44px;border-radius:6px;cursor:pointer;display:block}
 tr:hover td{background:var(--card2)}
 .speed{font-weight:700}
 .fast{color:var(--bad)} .mid{color:var(--warn)} .slow{color:var(--ok)}
__VIEWER_CSS__
 .evcol{position:relative;min-height:420px}
 .evcol .card{position:absolute;inset:0;display:flex;flex-direction:column}
 .evcol .card h3{flex:0 0 auto}
 .evscroll{flex:1;overflow:hidden}
 @media(max-width:900px){.evcol{min-height:0}
  .evcol .card{position:static}.evscroll{overflow:visible}}
 .save-msg{font-size:12px;color:var(--ok);margin-left:10px}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__
 <span style="flex:1"></span>
 <span class=chip><span id=dotS class=dot></span><span id=stStream>Stream</span></span>
 <span class=chip><span id=dotC class=dot></span><span id=stCal>Kalibrierung</span></span>
 <span class=chip id=stFps>- FPS</span></header>

<div class=wrap>
 <div>
  <div class=kpis>
   <div class=kpi><b id=kHeute>-</b><span>Fahrzeuge heute</span></div>
   <div class=kpi><b id=k24>-</b><span>Fahrzeuge (24 h)</span></div>
   <div class=kpi><b id=kAll>-</b><span>gesamt</span></div>
   <div class=kpi><b id=kAvg>-</b><span>&Oslash; km/h</span></div>
   <div class=kpi><b id=kMax>-</b><span>max km/h</span></div>
  </div>
  <div class=card><h3>Live</h3><img class=live src="/stream.mjpg">
   <div style="margin-top:10px;font-size:13px;color:var(--mut);display:flex;gap:16px;flex-wrap:wrap">
    <label style="cursor:pointer"><input type=checkbox id=ovBox
     onchange="saveOverlay()"> Boxen</label>
    <label style="cursor:pointer"><input type=checkbox id=ovTrail
     onchange="saveOverlay()"> Mess-Spur</label>
    <label style="cursor:pointer"><input type=checkbox id=ovZone
     onchange="saveOverlay()"> Bereich</label>
    <label style="cursor:pointer"><input type=checkbox id=ovLine
     onchange="saveOverlay()"> Linie</label>
    <label style="cursor:pointer" title="Diagnose: erkannte Bewegungspixel rot einfaerben">
     <input type=checkbox id=ovMask onchange="saveOverlay()"> Maske</label>
   </div></div>
 </div>
 <div class=evcol>
  <div class=card>
   <h3 style="display:flex;justify-content:space-between;align-items:center">
    Letzte Ereignisse &nbsp;<a href="/messungen"
     style="text-transform:none;font-weight:400">alle Messungen &rarr;</a>
    <button onclick="delAll()" style="background:var(--card2);color:var(--bad);
     font-size:11px;padding:5px 10px">alle l&ouml;schen</button></h3>
   <div class=evscroll>
   <table><thead><tr><th>Bild</th><th>Zeit</th><th>km/h</th><th></th>
    <th></th></tr></thead><tbody id=evb></tbody></table>
   </div>
  </div>
 </div>
</div>
__VIEWER_HTML__
<script>
function spdClass(v){return v>=50?'fast':(v>=30?'mid':'slow');}
function dirArrow(d){return d==='links->rechts'?'&#8594;':'&#8592;';}
async function tick(){
 try{
  const s=await (await fetch('/api/stats')).json();
  document.getElementById('dotS').className='dot'+(s.connected?' on':'');
  document.getElementById('dotC').className='dot'+(s.calibrated?' on':'');
  document.getElementById('stCal').textContent=
   s.calibrated?(s.has_line?'kalibriert + Linie':'kalibriert'):'nicht kalibriert';
  document.getElementById('stFps').textContent=
   s.fps+' FPS'+(s.tracking_on===false?' | '+s.tracking_reason:'')
   +(s.phase==='daemmerung'?' | D\u00e4mmerungs-Profil':'')
   +(s.phase==='nacht'?' | Nacht-Profil':'')
   +(s.hybrid&&s.hybrid!=='aus'?' | KI-Hybrid: '+s.hybrid:'');
  const t=s.totals||{};
  kHeute.textContent=t.heute??'-';
  k24.textContent=t.letzte_24h??'-'; kAll.textContent=t.anzahl??'-';
  kAvg.textContent=t.schnitt_kmh??'-'; kMax.textContent=t.max_kmh??'-';
  const raw=await (await fetch('/api/events?limit=30')).json();
  const ev=window.innerWidth<=900?raw.slice(0,10):raw;
  lastEvents=ev;
  evb.innerHTML=ev.map((e,i)=>{
   const d=new Date(e.ts*1000).toLocaleString('de-DE',
    {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
   const img=e.snapshot?`<img src="/snap/${e.snapshot}"
     onclick="openEv(${i})">`:'';
   return `<tr><td>${img}</td><td>${d}</td>`
    +`<td class="speed ${spdClass(e.speed_kmh)}" title="${e.distanz_m} m in ${e.dauer_s} s, ${e.samples} Messpunkte${e.residual_m!=null?', Fit-Fehler '+e.residual_m+' m':''}">${e.speed_kmh.toFixed(1)}</td>`
    +`<td>${dirArrow(e.richtung)}</td>`
    +`<td><a href="#" onclick="delEv(${e.id});return false"
       style="color:var(--bad)" title="Messung l\u00f6schen">&#10005;</a></td></tr>`;
  }).join('');
 }catch(e){}
}
async function delEv(id){
 await fetch('/api/events/'+id,{method:'DELETE'});tick();}
async function delAll(){
 if(!confirm('Wirklich ALLE Messungen samt Snapshots loeschen?'))return;
 await fetch('/api/events',{method:'DELETE'});tick();}
async function loadSettings(){
 const s=await (await fetch('/api/settings')).json();
 ovBox.checked=s.show_boxes; ovTrail.checked=s.show_trail;
 ovZone.checked=s.show_zone; ovLine.checked=s.show_line;
 ovMask.checked=s.show_mask;
}
async function saveOverlay(){
 await fetch('/api/settings',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({show_boxes:ovBox.checked,show_trail:ovTrail.checked,
   show_zone:ovZone.checked,show_line:ovLine.checked,
   show_mask:ovMask.checked})});
}
__VIEWER_JS__
setInterval(tick,2000);tick();loadSettings();
</script></body></html>
"""

CALIB_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Kalibrierung</title><style>""" + BASE_CSS + """
 canvas{max-width:100%;border:1px solid var(--line);cursor:crosshair;border-radius:10px}
 table{border-collapse:collapse;font-size:13px}
 td,th{padding:4px 6px;border-bottom:1px solid var(--line)}
 td input{width:64px;padding:5px 6px}
 .modes{margin:0 0 10px} .modes label{margin-right:14px;cursor:pointer;font-size:14px}
 .hint{max-width:540px;line-height:1.55;color:var(--mut);font-size:13px}
 .del{color:var(--bad);cursor:pointer;font-weight:700}
 .tgl{font-size:13px;color:var(--mut);margin-left:14px;cursor:pointer}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__</header>
<div class=subnav><a href="/calibrate" class=cur>Geometrie &amp; Messlinie</a>
 <a href="/referenzen">Referenzmessungen</a></div>
<div class=wrap>
 <div class=card>
  <div class=modes>
   <label><input type=radio name=mode value=points checked
    onchange="setMode('points')"> Kalibrier-Punkte</label>
   <label><input type=radio name=mode value=line
    onchange="setMode('line')"> Messlinie</label>
   <label><input type=radio name=mode value=zone
    onchange="setMode('zone')"> Messbereich</label>
   <label><input type=radio name=mode value=dist
    onchange="setMode('dist')"> Entzerrung</label>
   <label><input type=radio name=mode value=ruler
    onchange="setMode('ruler')"> Lineal</label>
   <label class=tgl><input type=checkbox id=gridToggle checked
    onchange="draw()"> Raster</label>
   <label class=tgl><input type=checkbox id=showPts checked
    onchange="draw()"> Punkte</label>
   <label class=tgl><input type=checkbox id=showLine checked
    onchange="draw()"> Linie</label>
   <label class=tgl><input type=checkbox id=showZone checked
    onchange="draw()"> Bereich</label>
   <label class=tgl><input type=checkbox id=showDist checked
    onchange="draw()"> Kanten</label>
   <label class=tgl><input type=checkbox id=loupeToggle checked> Lupe</label>
  </div>
  <canvas id=c></canvas>
  <p><button onclick="reload()">Neues Standbild</button>
     <button onclick="undo()" style="background:var(--card2)">R&uuml;ckg&auml;ngig</button>
     <button onclick="showGrid()" style="background:var(--ok);color:#052">
      Gitter (Server) pr&uuml;fen</button>
     <button onclick="view='dist';img.src='/motion_mask.jpg?'+Date.now()"
      style="background:var(--card2)">Bewegungsmaske</button></p>
  <p class=hint>&bdquo;Raster live&ldquo; rechnet das 1-m-Gitter direkt im
   Browser aus den aktuellen (auch ungespeicherten) Punkten &mdash; dicke Linien
   = 5 m. &bdquo;Gitter (Server)&ldquo; zeigt die tats&auml;chlich gespeicherte
   und aktive Kalibrierung.</p>
 </div>
 <div class=card>
  <div id=pointsPanel>
   <p class=hint>Klicke <b>&ge;4 Punkte</b>, die eine Fl&auml;che aufspannen
    (z.B. beide Fahrbahnr&auml;nder). Pixel- und Meterwerte sind direkt
    editierbar &mdash; der Punkt und das Live-Raster folgen sofort.</p>
   <table id=pts><thead><tr><th>#</th><th>X px</th><th>Y px</th>
    <th>X m</th><th>Y m</th><th></th></tr></thead><tbody></tbody></table>
   <p><button onclick="savePoints()">Kalibrierung speichern</button>
      <span id=msgP class=save-msg></span></p>
  </div>
  <div id=linePanel style="display:none">
   <p class=hint>2 Punkte quer &uuml;ber die Fahrbahn. Nur was die Linie
    &uuml;berquert, wird gewertet.</p>
   <p><button onclick="saveLine()">Messlinie speichern</button>
      <span id=msgL class=save-msg></span></p>
  </div>
  <div id=rulerPanel style="display:none">
   <p class=hint>Mess-Werkzeug: Klicke <b>2 Punkte</b> im Bild &mdash; angezeigt
    wird die Distanz in Metern laut aktueller Kalibrierung (inkl. Entzerrung
    und ungespeicherter &Auml;nderungen). Damit pr&uuml;fst du bekannte
    Strecken: Zaunpfosten (10 m?), Radstand eines parkenden Autos (~2,6 m),
    Fahrbahnbreite. Weicht der Wert ab, stimmt die Kalibrierung <b>an dieser
    Stelle</b> nicht.</p>
   <p id=rulerOut style="font-size:22px;font-weight:700">&mdash;</p>
  </div>
  <div id=distPanel style="display:none">
   <p class=hint>Fisheye-Korrektur: Klicke <b>&ge;4 Punkte entlang einer real
    schnurgeraden Kante</b> (Bordstein, Zaun, Pflasterfuge) &mdash; m&ouml;glichst
    &uuml;ber die ganze Bildbreite und <b>nicht durch die Bildmitte</b>. Dann
    &bdquo;Linie abschlie&szlig;en&ldquo; und weitere Kanten erfassen (2&ndash;3
    Linien in unterschiedlicher Bildh&ouml;he sind ideal). Zum Schluss
    berechnen &mdash; das Raster ber&uuml;cksichtigt die Kr&uuml;mmung danach
    automatisch.</p>
   <p id=distInfo class=hint></p>
   <p><button onclick="finishDistLine()">Linie abschlie&szlig;en</button>
      <button onclick="calcDist()">Entzerrung berechnen</button>
      <button onclick="showPreview()"
       style="background:var(--card2)">Entzerrte Vorschau</button>
      <button onclick="clearDist()" style="background:var(--card2);color:var(--bad)">
       Entzerrung l&ouml;schen</button>
      <span id=msgD class=save-msg></span></p>
  </div>
  <div id=zonePanel style="display:none">
   <p class=hint>&ge;3 Punkte f&uuml;r den Messbereich &mdash; nur dort werden
    Messpunkte gesammelt. Beim Fisheye mittig bleiben.</p>
   <p><button onclick="saveZone()">Messbereich speichern</button>
      <button onclick="clearZone()" style="background:var(--card2);color:var(--bad)">
       Bereich l&ouml;schen</button>
      <span id=msgZ class=save-msg></span></p>
  </div>
 </div>
</div>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
const img=new Image();
let pts=[],linePts=[],zonePts=[],mode='points';
let dist=null,distLines=[],curLine=[],rulerPts=[];
function num(v){return parseFloat(String(v).trim().replace(',','.'));}
let view='dist';
function reload(){view='dist';img.src='/snapshot.jpg?'+Date.now();}
function showGrid(){view='dist';img.src='/calib_grid.jpg?'+Date.now();}
function showPreview(){view='undist';img.src='/undistort_preview.jpg?'+Date.now();}
function V(p){if(view!=='undist')return p;
 const u=undistP([p.x,p.y]);return u?{x:u[0],y:u[1]}:null;}
img.onload=()=>{if(!cv.width||img.src.indexOf('calib_grid')<0){
 cv.width=img.width;cv.height=img.height;}draw();};

function setMode(m){mode=m;
 pointsPanel.style.display=m==='points'?'':'none';
 linePanel.style.display=m==='line'?'':'none';
 zonePanel.style.display=m==='zone'?'':'none';
 distPanel.style.display=m==='dist'?'':'none';
 rulerPanel.style.display=m==='ruler'?'':'none';draw();}

function mark(p,color,label){ctx.fillStyle=color;ctx.beginPath();
 ctx.arc(p.x,p.y,2.5,0,7);ctx.fill();ctx.strokeStyle='rgba(255,255,255,.7)';
 ctx.lineWidth=.75;ctx.stroke();
 if(label){ctx.fillStyle=color;ctx.font='10px sans-serif';
  ctx.fillText(label,p.x+5,p.y-4);}}

function draw(){
 ctx.drawImage(img,0,0);
 if(gridToggle.checked)drawLiveGrid();
 const zp=zonePts.map(V).filter(x=>x),lp=linePts.map(V).filter(x=>x);
 const dl=distLines.map(l=>l.map(V).filter(x=>x)),
       cl=curLine.map(V).filter(x=>x);
 if(showZone.checked&&zp.length){ctx.strokeStyle='#4f8ef7';
  ctx.fillStyle='rgba(79,142,247,.08)';ctx.lineWidth=1;ctx.beginPath();
  ctx.moveTo(zp[0].x,zp[0].y);
  zp.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));
  if(zp.length>2){ctx.closePath();ctx.fill();}ctx.stroke();
  zp.forEach(p=>mark(p,'#4f8ef7'));}
 if(showLine.checked&&lp.length){ctx.strokeStyle='#ff6b6b';ctx.lineWidth=1;ctx.beginPath();
  ctx.moveTo(lp[0].x,lp[0].y);
  if(lp[1])ctx.lineTo(lp[1].x,lp[1].y);ctx.stroke();
  lp.forEach(p=>mark(p,'#ff6b6b'));}
 if(showDist.checked)dl.forEach(l=>{if(!l.length)return;
  ctx.strokeStyle='#22d3ee';ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(l[0].x,l[0].y);
  l.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.stroke();
  l.forEach(p=>mark(p,'#22d3ee'));});
 if(cl.length){ctx.strokeStyle='#ffb454';ctx.lineWidth=1;ctx.beginPath();
  ctx.moveTo(cl[0].x,cl[0].y);
  cl.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.stroke();
  cl.forEach(p=>mark(p,'#ffb454'));}
 if(rulerPts.length){const rp=rulerPts.map(V).filter(x=>x);
  if(rp.length){ctx.strokeStyle='#e879f9';ctx.lineWidth=1.5;ctx.beginPath();
   ctx.moveTo(rp[0].x,rp[0].y);
   if(rp[1])ctx.lineTo(rp[1].x,rp[1].y);ctx.stroke();
   rp.forEach(p=>mark(p,'#e879f9'));
   if(rp.length===2&&rulerDist!==null){
    ctx.fillStyle='#e879f9';ctx.font='bold 14px sans-serif';
    ctx.fillText(rulerDist.toFixed(2)+' m',
     (rp[0].x+rp[1].x)/2+6,(rp[0].y+rp[1].y)/2-6);}}}
 if(showPts.checked)pts.forEach((p,i)=>{
  const v=V(p);if(v)mark(v,'#3ddc84',String(i+1));});
 drawLoupe();
 distStatus();
}
function distStatus(){
 const el=document.getElementById('distInfo');if(!el)return;
 el.textContent=(dist?`aktiv: \u03bb=${dist.lambda} \u00b7 `:'nicht aktiv \u00b7 ')
  +`${distLines.length} Linie(n) erfasst`
  +(curLine.length?` + aktuelle mit ${curLine.length} Punkt(en)`:'');}

/* ---- Fisheye (Division Model) ---- */
function undistP(p){if(!dist)return p;
 const nx=(p[0]-dist.cx)/dist.scale,ny=(p[1]-dist.cy)/dist.scale;
 const den=1+dist.lambda*(nx*nx+ny*ny);if(den<0.05)return null;
 const f=1/den;
 return [dist.cx+dist.scale*nx*f,dist.cy+dist.scale*ny*f];}
function redistP(p){if(!dist)return p;
 const ux=(p[0]-dist.cx)/dist.scale,uy=(p[1]-dist.cy)/dist.scale;
 const ru=Math.hypot(ux,uy);
 if(ru<1e-9||Math.abs(dist.lambda)<1e-12)return p;
 const disc=1-4*dist.lambda*ru*ru;if(disc<0)return null;
 const rd=(1-Math.sqrt(disc))/(2*dist.lambda*ru),s=rd/ru;
 if(s<0.4||s>2.5)return null;
 return [dist.cx+dist.scale*ux*s,dist.cy+dist.scale*uy*s];}

/* ---- Homographie im Browser (DLT + Normalgleichungen) ---- */
function normT(P){
 const mx=P.reduce((s,p)=>s+p[0],0)/P.length,
       my=P.reduce((s,p)=>s+p[1],0)/P.length;
 const md=P.reduce((s,p)=>s+Math.hypot(p[0]-mx,p[1]-my),0)/P.length;
 const s=md>1e-9?Math.SQRT2/md:1;
 return [[s,0,-s*mx],[0,s,-s*my],[0,0,1]];
}
function mat3mul(A,B){
 const C=[[0,0,0],[0,0,0],[0,0,0]];
 for(let i=0;i<3;i++)for(let j=0;j<3;j++)
  for(let k=0;k<3;k++)C[i][j]+=A[i][k]*B[k][j];
 return C;
}
function computeH(){
 const P=pts.filter(p=>p.wx!==''&&p.wy!==''
  &&!isNaN(num(p.wx))&&!isNaN(num(p.wy)));
 if(P.length<4)return null;
 const pairs=P.map(p=>({u:undistP([p.x,p.y]),
   w:[num(p.wx),num(p.wy)]})).filter(q=>q.u);
 if(pairs.length<4)return null;
 const ip=pairs.map(q=>q.u), wp=pairs.map(q=>q.w);
 // Hartley-Normalisierung: ohne sie ist die DLT auf Pixelkoordinaten
 // numerisch instabil (kleine Klick-Abweichung -> grosse Rasterfehler)
 const Ti=normT(ip), Tw=normT(wp);
 const nrm=(T,p)=>[T[0][0]*p[0]+T[0][2], T[1][1]*p[1]+T[1][2]];
 const A=[],b=[];
 for(let k=0;k<ip.length;k++){
  const [x,y]=nrm(Ti,ip[k]), [X,Y]=nrm(Tw,wp[k]);
  A.push([x,y,1,0,0,0,-X*x,-X*y]);b.push(X);
  A.push([0,0,0,x,y,1,-Y*x,-Y*y]);b.push(Y);}
 const n=8,M=Array.from({length:n},()=>new Array(n+1).fill(0));
 for(let r=0;r<A.length;r++)for(let i=0;i<n;i++){
  for(let j=0;j<n;j++)M[i][j]+=A[r][i]*A[r][j];M[i][n]+=A[r][i]*b[r];}
 for(let i=0;i<n;i++){let piv=i;
  for(let k=i+1;k<n;k++)if(Math.abs(M[k][i])>Math.abs(M[piv][i]))piv=k;
  [M[i],M[piv]]=[M[piv],M[i]];
  if(Math.abs(M[i][i])<1e-12)return null;
  for(let k=i+1;k<n;k++){const f=M[k][i]/M[i][i];
   for(let j=i;j<=n;j++)M[k][j]-=f*M[i][j];}}
 const h=new Array(n);
 for(let i=n-1;i>=0;i--){let s=M[i][n];
  for(let j=i+1;j<n;j++)s-=M[i][j]*h[j];h[i]=s/M[i][i];}
 const Hn=[[h[0],h[1],h[2]],[h[3],h[4],h[5]],[h[6],h[7],1]];
 const TwInv=inv3(Tw);if(!TwInv)return null;
 return mat3mul(mat3mul(TwInv,Hn),Ti);
}
function inv3(m){
 const a=m[0][0],b=m[0][1],c=m[0][2],d=m[1][0],e=m[1][1],f=m[1][2],
       g=m[2][0],h=m[2][1],i=m[2][2];
 const A=e*i-f*h,B=c*h-b*i,C=b*f-c*e,D=f*g-d*i,E=a*i-c*g,F=c*d-a*f,
       G=d*h-e*g,Hh=b*g-a*h,I=a*e-b*d;
 const det=a*A+b*D+c*G;if(Math.abs(det)<1e-12)return null;
 return [[A/det,B/det,C/det],[D/det,E/det,F/det],[G/det,Hh/det,I/det]];
}
function applyH(H,x,y){
 const w=H[2][0]*x+H[2][1]*y+H[2][2];
 return [(H[0][0]*x+H[0][1]*y+H[0][2])/w,
         (H[1][0]*x+H[1][1]*y+H[1][2])/w, w];}
function drawWLine(Hi,a,b,major){
 ctx.lineWidth=major?1.2:.5;ctx.beginPath();let pen=false;const N=32;
 for(let i=0;i<=N;i++){const t=i/N;
  const ph=applyH(Hi,a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t);
  const p=view==='undist'?[ph[0],ph[1]]:redistP([ph[0],ph[1]]);
  const ok=p!==null&&ph[2]>1e-6&&p[0]>-cv.width&&p[0]<2*cv.width
        &&p[1]>-cv.height&&p[1]<2*cv.height;
  if(ok){if(!pen){ctx.moveTo(p[0],p[1]);pen=true;}else ctx.lineTo(p[0],p[1]);}
  else pen=false;}
 ctx.stroke();}
function drawLiveGrid(){
 const H=computeH();if(!H)return;const Hi=inv3(H);if(!Hi)return;
 const wv=pts.filter(p=>!isNaN(num(p.wx))&&!isNaN(num(p.wy)))
   .map(p=>[num(p.wx),num(p.wy)]);
 const wxs=wv.map(v=>v[0]),wys=wv.map(v=>v[1]);
 const cxw=wxs.reduce((a,b)=>a+b,0)/wxs.length,
       cyw=wys.reduce((a,b)=>a+b,0)/wys.length;
 const spanx=Math.max(Math.max(...wxs)-Math.min(...wxs),2),
       spany=Math.max(Math.max(...wys)-Math.min(...wys),2);
 let xmin=Math.max(cxw-spanx,-40),xmax=Math.min(cxw+spanx,40),
     ymin=Math.max(cyw-spany,-40),ymax=Math.min(cyw+spany,40);
 ctx.strokeStyle='rgba(61,220,132,.5)';
 for(let x=Math.ceil(xmin);x<=xmax;x++)
  drawWLine(Hi,[x,ymin],[x,ymax],x%5===0);
 for(let y=Math.ceil(ymin);y<=ymax;y++)
  drawWLine(Hi,[xmin,y],[xmax,y],y%5===0);
}

/* ---- Interaktion ---- */
let mouse=null;
cv.onmousemove=e=>{if(!loupeToggle.checked){mouse=null;return;}
 const r=cv.getBoundingClientRect();
 mouse={x:(e.clientX-r.left)*cv.width/r.width,
        y:(e.clientY-r.top)*cv.height/r.height};
 requestAnimationFrame(draw);};
cv.onmouseleave=()=>{mouse=null;requestAnimationFrame(draw);};
function drawLoupe(){
 if(!mouse||!loupeToggle.checked)return;
 const Z=4,R=48;
 const ly=mouse.y>R*2+20?mouse.y-R-16:mouse.y+R+16;
 ctx.save();
 ctx.beginPath();ctx.arc(mouse.x,ly,R,0,7);ctx.clip();
 ctx.drawImage(img,mouse.x-R/Z,mouse.y-R/Z,2*R/Z,2*R/Z,
               mouse.x-R,ly-R,2*R,2*R);
 ctx.restore();
 ctx.strokeStyle='#fff';ctx.lineWidth=1;
 ctx.beginPath();ctx.arc(mouse.x,ly,R,0,7);ctx.stroke();
 ctx.strokeStyle='rgba(255,80,80,.9)';
 ctx.beginPath();ctx.moveTo(mouse.x-8,ly);ctx.lineTo(mouse.x+8,ly);
 ctx.moveTo(mouse.x,ly-8);ctx.lineTo(mouse.x,ly+8);ctx.stroke();
}
cv.onclick=e=>{const r=cv.getBoundingClientRect();
 const sx=cv.width/r.width,sy=cv.height/r.height;
 let p={x:(e.clientX-r.left)*sx,y:(e.clientY-r.top)*sy};
 if(view==='undist'){const d0=redistP([p.x,p.y]);
  if(!d0)return;p={x:d0[0],y:d0[1]};}
 if(mode==='points'){pts.push({...p,wx:'',wy:''});renderTable();}
 else if(mode==='line'){if(linePts.length>=2)linePts=[];linePts.push(p);draw();}
 else if(mode==='zone'){zonePts.push(p);draw();}
 else if(mode==='ruler'){if(rulerPts.length>=2)rulerPts=[];
  rulerPts.push(p);updateRuler();draw();}
 else{curLine.push(p);draw();}};
function undo(){if(mode==='points'){pts.pop();renderTable();}
 else if(mode==='line'){linePts.pop();draw();}
 else if(mode==='zone'){zonePts.pop();draw();}
 else if(mode==='ruler'){rulerPts.pop();updateRuler();draw();}
 else{if(curLine.length)curLine.pop();else distLines.pop();draw();}}
function updPt(i,k,v){const f=num(v);
 if(k==='x'||k==='y'){if(!isNaN(f))pts[i][k]=f;}else pts[i][k]=v;draw();}
function delPt(i){pts.splice(i,1);renderTable();}
function renderTable(){draw();
 document.querySelector('#pts tbody').innerHTML=pts.map((p,i)=>
  `<tr><td>${i+1}</td>`
  +`<td><input value="${Math.round(p.x*10)/10}" oninput="updPt(${i},'x',this.value)"></td>`
  +`<td><input value="${Math.round(p.y*10)/10}" oninput="updPt(${i},'y',this.value)"></td>`
  +`<td><input value="${p.wx}" oninput="updPt(${i},'wx',this.value)"></td>`
  +`<td><input value="${p.wy}" oninput="updPt(${i},'wy',this.value)"></td>`
  +`<td><span class=del onclick="delPt(${i})">&#10005;</span></td></tr>`
 ).join('');}

/* ---- Laden & Speichern ---- */
async function loadCalib(){
 try{
  const c=await (await fetch('/api/calibration')).json();
  if(c.image_points&&c.world_points)
   pts=c.image_points.map((p,i)=>({x:p[0],y:p[1],
    wx:c.world_points[i][0],wy:c.world_points[i][1]}));
  if(c.trigger_line)linePts=c.trigger_line.map(p=>({x:p[0],y:p[1]}));
  if(c.zone)zonePts=c.zone.map(p=>({x:p[0],y:p[1]}));
  dist=c.distortion||null;
  renderTable();
 }catch(e){}
}
async function post(body,msgEl,okText){
 const r=await fetch('/api/calibration',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const j=await r.json();
 document.getElementById(msgEl).textContent=
  j.ok?okText+(j.warn||''):'Fehler: '+j.error;}
async function savePoints(){
 const ip=pts.map(p=>[Math.round(p.x*10)/10,Math.round(p.y*10)/10]);
 const wp=pts.map(p=>[num(p.wx),num(p.wy)]);
 if(ip.length<4||wp.some(w=>isNaN(w[0])||isNaN(w[1]))){
  msgP.textContent='alle Felder ausfuellen';return;}
 post({image_points:ip,world_points:wp},'msgP','gespeichert & aktiv');}
async function saveLine(){
 if(linePts.length!==2){msgL.textContent='genau 2 Punkte setzen';return;}
 post({trigger_line:linePts.map(p=>[Math.round(p.x),Math.round(p.y)])},
  'msgL','gespeichert & aktiv');}
async function saveZone(){
 if(zonePts.length<3){msgZ.textContent='mind. 3 Punkte setzen';return;}
 post({zone:zonePts.map(p=>[Math.round(p.x),Math.round(p.y)])},
  'msgZ','gespeichert & aktiv');}
let rulerDist=null;
function updateRuler(){
 rulerDist=null;
 const out=document.getElementById('rulerOut');
 if(rulerPts.length<2){out.innerHTML='&mdash;';return;}
 const H=computeH();
 if(!H){out.textContent='erst >=4 Kalibrierpunkte mit Metern eintragen';return;}
 const u1=undistP([rulerPts[0].x,rulerPts[0].y]),
       u2=undistP([rulerPts[1].x,rulerPts[1].y]);
 if(!u1||!u2){out.textContent='Punkt ausserhalb des Entzerrungsbereichs';return;}
 const w1=applyH(H,u1[0],u1[1]),w2=applyH(H,u2[0],u2[1]);
 const dx=Math.abs(w2[0]-w1[0]),dy=Math.abs(w2[1]-w1[1]);
 rulerDist=Math.hypot(dx,dy);
 out.innerHTML=rulerDist.toFixed(2)+' m '
  +`<span style="font-size:13px;color:var(--mut)">(l\u00e4ngs ${dx.toFixed(2)} \u00b7 quer ${dy.toFixed(2)})</span>`;
}
async function clearZone(){zonePts=[];draw();post({zone:[]},'msgZ','Bereich entfernt');}
function finishDistLine(){
 if(curLine.length<4){msgD.textContent='mind. 4 Punkte je Linie';return;}
 distLines.push(curLine);curLine=[];msgD.textContent='';draw();}
async function calcDist(){
 const all=[...distLines];if(curLine.length>=4)all.push(curLine);
 if(!all.length){msgD.textContent='erst Linien erfassen';return;}
 msgD.textContent='rechne...';
 const r=await fetch('/api/distortion',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({lines:all.map(l=>l.map(p=>[p.x,p.y])),
   width:cv.width,height:cv.height})});
 const j=await r.json();
 if(j.ok){msgD.textContent=`\u03bb=${j.lambda}, Kruemmung -${j.verbesserung}%`+(j.hint||'');
  await loadCalib();}
 else msgD.textContent='Fehler: '+j.error;}
async function clearDist(){
 await fetch('/api/distortion',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({clear:true})});
 dist=null;distLines=[];curLine=[];msgD.textContent='entfernt';draw();}
reload();loadCalib();
</script></body></html>
"""

STATS_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TrafficCam Statistik</title><style>""" + BASE_CSS + """
 .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}
 @media(max-width:900px){.kpis{grid-template-columns:repeat(3,1fr)}}
 .kpi{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
 .kpi b{font-size:20px;display:block}
 .kpi span{font-size:11px;color:var(--mut)}
 canvas{width:100%;height:190px;display:block}
 .rangebtn{background:var(--card2);color:var(--txt);margin-right:6px}
 .rangebtn.on{background:var(--acc)}
 .wrap2{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:18px;
  max-width:1500px;margin:0 auto}
 @media(max-width:900px){.wrap2{grid-template-columns:1fr}}
 .dirrow{font-size:14px;color:var(--mut);margin-top:8px}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__
 <span style="flex:1"></span>
 <span>
  <button class="rangebtn" data-r=24h onclick="setRange('24h')">24 h</button>
  <button class="rangebtn on" data-r=7d onclick="setRange('7d')">7 Tage</button>
  <button class="rangebtn" data-r=30d onclick="setRange('30d')">30 Tage</button>
  <button class="rangebtn" data-r=all onclick="setRange('all')">alles</button>
 </span></header>
<div style="padding:18px 18px 0;max-width:1500px;margin:0 auto">
 <div class=kpis>
  <div class=kpi><b id=kN>-</b><span>Fahrzeuge</span></div>
  <div class=kpi><b id=kAvg>-</b><span>&Oslash; km/h</span></div>
  <div class=kpi><b id=kMed>-</b><span>Median</span></div>
  <div class=kpi><b id=kV85>-</b><span>V85</span></div>
  <div class=kpi><b id=kMax>-</b><span>max km/h</span></div>
  <div class=kpi><b id=kLim>-</b><span id=kLimLbl>&gt; Limit</span></div>
 </div>
</div>
<div class=wrap2>
 <div class=card><h3>Geschwindigkeitsverteilung (km/h)</h3>
  <canvas id=cHist></canvas><div class=dirrow id=dirInfo></div></div>
 <div class=card><h3>Fahrzeuge je Stunde</h3><canvas id=cHourN></canvas></div>
 <div class=card><h3>&Oslash; km/h je Stunde</h3><canvas id=cHourV></canvas></div>
 <div class=card><h3>Letzte 14 Tage (Anzahl, Beschriftung: &Oslash;)</h3>
  <canvas id=cDays></canvas></div>
</div>
<script>
let range='7d';
let tip=null;
function ensureTip(){if(tip)return;
 tip=document.createElement('div');
 tip.style.cssText='position:fixed;pointer-events:none;display:none;'
  +'background:#1a2030;border:1px solid #232a3d;padding:5px 9px;'
  +'border-radius:7px;font-size:12px;color:#e8eaf2;z-index:30;'
  +'box-shadow:0 4px 14px rgba(0,0,0,.4)';
 document.body.appendChild(tip);}
function setRange(r){range=r;
 document.querySelectorAll('.rangebtn').forEach(b=>
  b.classList.toggle('on',b.dataset.r===r));
 load();}
function bars(id,labels,vals,opts){
 opts=opts||{};ensureTip();
 const c=document.getElementById(id),dpr=window.devicePixelRatio||1;
 const W=c.clientWidth,H=c.clientHeight;
 c.width=W*dpr;c.height=H*dpr;
 const x=c.getContext('2d');x.scale(dpr,dpr);
 const padL=30,padB=20,padT=12;
 const iw=W-padL-6,ih=H-padT-padB;
 const mx=Math.max(...vals,opts.hline||0,1);
 x.strokeStyle='#232a3d';x.beginPath();
 x.moveTo(padL,padT+ih);x.lineTo(padL+iw,padT+ih);x.stroke();
 const bw=iw/vals.length;
 x.fillStyle=opts.color||'#4f8ef7';
 vals.forEach((v,i)=>{const h=v/mx*ih;
  x.fillRect(padL+i*bw+1,padT+ih-h,Math.max(bw-2,1),h);});
 x.fillStyle='#8b93ab';x.font='10px sans-serif';
 const step=Math.ceil(labels.length/12);
 labels.forEach((l,i)=>{if(i%step)return;
  x.fillText(l,padL+i*bw,padT+ih+13);});
 x.textAlign='right';
 x.fillText(String(Math.round(mx)),padL-4,padT+8);
 x.fillText('0',padL-4,padT+ih);
 x.textAlign='left';
 if(opts.hline){const y=padT+ih-opts.hline/mx*ih;
  x.strokeStyle='#ff6b6b';x.setLineDash([4,4]);x.beginPath();
  x.moveTo(padL,y);x.lineTo(padL+iw,y);x.stroke();x.setLineDash([]);
  x.fillStyle='#ff6b6b';x.fillText(opts.hlineLabel||'',padL+4,y-4);}
 if(opts.valueLabels){x.fillStyle='#8b93ab';
  opts.valueLabels.forEach((t,i)=>{if(!t)return;
   x.save();x.translate(padL+i*bw+bw/2,padT+ih-4);
   x.textAlign='center';x.fillText(t,0,-2);x.restore();});}
 // Hover-Tooltip: Balken unter dem Cursor anzeigen
 c._chart={padL,bw,n:vals.length,tip:opts.tip||((i)=>labels[i]+': '+vals[i])};
 if(!c._tipBound){c._tipBound=true;
  c.onmousemove=e=>{const ch=c._chart;if(!ch)return;
   const r=c.getBoundingClientRect();
   const px=(e.clientX-r.left)*(c.clientWidth/r.width);
   const i=Math.floor((px-ch.padL)/ch.bw);
   if(i<0||i>=ch.n){tip.style.display='none';return;}
   tip.textContent=ch.tip(i);
   tip.style.left=(e.clientX+14)+'px';
   tip.style.top=(e.clientY-30)+'px';
   tip.style.display='block';};
  c.onmouseleave=()=>{tip.style.display='none';};}
}
async function load(){
 const s=await (await fetch('/api/statistics?range='+range)).json();
 const k=s.kpi;
 kN.textContent=k.anzahl;kAvg.textContent=k.avg;kMed.textContent=k.median;
 kV85.textContent=k.v85;kMax.textContent=k.max;
 kLim.textContent=k.ueber_limit_pct+' %';
 kLimLbl.textContent='> '+k.limit+' km/h';
 bars('cHist',s.bins.map(b=>b+''),s.hist,{color:'#4f8ef7',
  tip:i=>`${s.bins[i]}\u2013${s.bins[i]+5} km/h: ${s.hist[i]} Fahrzeuge`});
 bars('cHourN',[...Array(24).keys()].map(h=>h+''),s.hour_n,{color:'#3ddc84',
  tip:i=>`${i}:00\u2013${i+1}:00 Uhr: ${s.hour_n[i]} Fahrzeuge`});
 bars('cHourV',[...Array(24).keys()].map(h=>h+''),s.hour_avg,
  {color:'#ffb454',hline:k.limit,hlineLabel:k.limit+' km/h',
   tip:i=>`${i}:00\u2013${i+1}:00 Uhr: \u00d8 ${s.hour_avg[i]} km/h (${s.hour_n[i]} Fzg.)`});
 bars('cDays',s.days,s.day_n,{color:'#22d3ee',
  valueLabels:s.day_avg.map(v=>v?String(v):''),
  tip:i=>`${s.days[i]}: ${s.day_n[i]} Fahrzeuge, \u00d8 ${s.day_avg[i]||'-'} km/h`});
 dirInfo.innerHTML=s.richtung.map(r=>
  `${r.richtung==='links->rechts'?'&#8594;':'&#8592;'} ${r.n} Fzg., &Oslash; ${r.avg}, Median ${r.median} km/h`)
  .join(' &nbsp;&middot;&nbsp; ');
 // Symmetrie-Check: beide Richtungen sollten aehnlich verteilt sein
 const dirs=s.richtung.filter(r=>r.n>=20&&r.median>0);
 if(dirs.length===2){
  const m1=dirs[0].median,m2=dirs[1].median;
  const rel=Math.abs(m1-m2)/((m1+m2)/2)*100;
  if(rel>12){
   dirInfo.innerHTML+=`<br><span style="color:var(--warn)">&#9888;
    Richtungs-Mediane weichen ${rel.toFixed(0)}% voneinander ab - da beide
    Richtungen auf verschiedenen Spuren fahren, deutet das auf eine
    Kalibrierungs-Schieflage einer Fahrbahnseite hin (Referenzmessungen
    auf der abweichenden Spur helfen).</span>`;
  }else{
   dirInfo.innerHTML+=`<br><span style="color:var(--ok)">Richtungs-Symmetrie
    ok (${rel.toFixed(0)}% Abweichung der Mediane)</span>`;
  }
 }
}
load();
</script></body></html>
"""

REFINE_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Referenzmessungen</title><style>""" + BASE_CSS + """
 canvas{max-width:100%;border:1px solid var(--line);cursor:crosshair;border-radius:10px}
 .gallery{display:flex;gap:8px;overflow-x:auto;padding-bottom:8px;margin-bottom:12px}
 .gallery img{height:70px;border-radius:6px;cursor:pointer;
  border:2px solid transparent;flex:0 0 auto}
 .gallery img.sel{border-color:var(--acc)}
 table{border-collapse:collapse;font-size:13px;width:100%}
 td,th{padding:5px 8px;border-bottom:1px solid var(--line)}
 .hint{max-width:560px;line-height:1.55;color:var(--mut);font-size:13px}
 input[type=text],input[type=number]{padding:6px 8px}
 .errgood{color:var(--ok)} .errmid{color:var(--warn)} .errbad{color:var(--bad)}
 .ptrow{display:flex;gap:8px;align-items:center;margin:4px 0;font-size:13px}
 .ptrow span{color:var(--mut);min-width:150px}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__</header>
<div class=subnav><a href="/calibrate">Geometrie &amp; Messlinie</a>
 <a href="/referenzen" class=cur>Referenzmessungen</a></div>
<div class=wrap>
 <div class=card>
  <p class=hint>1) Snapshot aus den letzten Messungen w&auml;hlen &middot;
   2) zwei Punkte anklicken (z.B. beide Radaufstandspunkte, Abstand = Radstand)
   &middot; 3) reale L&auml;nge eintragen &middot; 4) Referenz hinzuf&uuml;gen.
   Mehrere Referenzen von verschiedenen Fahrzeugen/Stellen erh&ouml;hen die
   Genauigkeit.</p>
  <div class=gallery id=gallery></div>
  <canvas id=c></canvas>
  <p>
   <input type=text id=refLen placeholder="reale L&auml;nge in m, z.B. 2,60"
    style="width:160px">
   <button onclick="addRef()">Referenz hinzuf&uuml;gen</button>
   <button onclick="curPts=[];draw()" style="background:var(--card2)">Punkte l&ouml;schen</button>
  </p>
  <p style="font-size:12px;color:var(--mut)">Typische Radst&auml;nde: Kleinwagen
   ~2,45 m &middot; Kompaktklasse (Golf etc.) ~2,60 m &middot; Kombi/Mittelklasse
   ~2,70&ndash;2,85 m &middot; SUV ~2,70&ndash;2,90 m. Genauer: Herstellerangabe
   des jeweiligen Fahrzeugs nachschlagen.</p>
 </div>
 <div class=card>
  <h3>Unsichere Punkte</h3>
  <p class=hint>Punkte abw&auml;hlen, die du <b>nicht</b> exakt vermessen hast
   (z.B. per Maßband/Triangulation) &mdash; nur diese werden optimiert. Fest
   angehakte Punkte bleiben unver&auml;ndert.</p>
  <div id=ptlist></div>
  <h3 style="margin-top:18px">Referenzmessungen</h3>
  <table id=refTbl><thead><tr><th>L&auml;nge</th><th>aktuell</th>
   <th>Fehler</th><th></th></tr></thead><tbody></tbody></table>
  <p><button onclick="doRefine()">Kalibrierung verfeinern</button>
     <span id=msgR class=save-msg></span></p>
  <div id=resultBox style="display:none;margin-top:12px">
   <h3>Ergebnis</h3>
   <table id=resTbl><thead><tr><th>L&auml;nge</th><th>neu</th>
    <th>Fehler</th></tr></thead><tbody></tbody></table>
   <p><button onclick="apply()">Vorschlag &uuml;bernehmen &amp; speichern</button>
      <a href="/calibrate" style="margin-left:10px">Danach: Gitter pr&uuml;fen &rarr;</a></p>
  </div>
 </div>
</div>
<script>
function num(v){return parseFloat(String(v).trim().replace(',','.'));}
let calib={image_points:[],world_points:[],distortion:null};
let fixedMask=[];
let refs=[];      // {p1,p2,length}
let curPts=[];
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
const img=new Image();
img.onload=()=>{cv.width=img.width;cv.height=img.height;draw();};

function undistP(p){const d=calib.distortion;if(!d)return p;
 const nx=(p[0]-d.cx)/d.scale,ny=(p[1]-d.cy)/d.scale;
 const den=1+d.lambda*(nx*nx+ny*ny);if(den<0.05)return null;
 const f=1/den;return [d.cx+d.scale*nx*f,d.cy+d.scale*ny*f];}
function normT(P){const mx=P.reduce((s,p)=>s+p[0],0)/P.length,
 my=P.reduce((s,p)=>s+p[1],0)/P.length;
 const md=P.reduce((s,p)=>s+Math.hypot(p[0]-mx,p[1]-my),0)/P.length;
 const s=md>1e-9?Math.SQRT2/md:1;return [[s,0,-s*mx],[0,s,-s*my],[0,0,1]];}
function mat3mul(A,B){const C=[[0,0,0],[0,0,0],[0,0,0]];
 for(let i=0;i<3;i++)for(let j=0;j<3;j++)for(let k=0;k<3;k++)C[i][j]+=A[i][k]*B[k][j];
 return C;}
function inv3(m){const a=m[0][0],b=m[0][1],c=m[0][2],d=m[1][0],e=m[1][1],
 f=m[1][2],g=m[2][0],h=m[2][1],i=m[2][2];
 const A=e*i-f*h,B=c*h-b*i,C=b*f-c*e,D=f*g-d*i,E=a*i-c*g,F=c*d-a*f,
 G=d*h-e*g,Hh=b*g-a*h,I=a*e-b*d;
 const det=a*A+b*D+c*G;if(Math.abs(det)<1e-12)return null;
 return [[A/det,B/det,C/det],[D/det,E/det,F/det],[G/det,Hh/det,I/det]];}
function computeH(){
 const pairs=calib.image_points.map((p,i)=>({u:undistP(p),w:calib.world_points[i]}))
  .filter(q=>q.u);
 if(pairs.length<4)return null;
 const Ti=normT(pairs.map(q=>q.u)),Tw=normT(pairs.map(q=>q.w));
 const nrm=(T,p)=>[T[0][0]*p[0]+T[0][2],T[1][1]*p[1]+T[1][2]];
 const A=[],b=[];
 for(let k=0;k<pairs.length;k++){
  const [x,y]=nrm(Ti,pairs[k].u),[X,Y]=nrm(Tw,pairs[k].w);
  A.push([x,y,1,0,0,0,-X*x,-X*y]);b.push(X);
  A.push([0,0,0,x,y,1,-Y*x,-Y*y]);b.push(Y);}
 const n=8,M=Array.from({length:n},()=>new Array(n+1).fill(0));
 for(let r=0;r<A.length;r++)for(let i=0;i<n;i++){
  for(let j=0;j<n;j++)M[i][j]+=A[r][i]*A[r][j];M[i][n]+=A[r][i]*b[r];}
 for(let i=0;i<n;i++){let piv=i;
  for(let k=i+1;k<n;k++)if(Math.abs(M[k][i])>Math.abs(M[piv][i]))piv=k;
  [M[i],M[piv]]=[M[piv],M[i]];if(Math.abs(M[i][i])<1e-12)return null;
  for(let k=i+1;k<n;k++){const f=M[k][i]/M[i][i];
   for(let j=i;j<=n;j++)M[k][j]-=f*M[i][j];}}
 const h=new Array(n);
 for(let i=n-1;i>=0;i--){let s=M[i][n];
  for(let j=i+1;j<n;j++)s-=M[i][j]*h[j];h[i]=s/M[i][i];}
 const Hn=[[h[0],h[1],h[2]],[h[3],h[4],h[5]],[h[6],h[7],1]];
 const TwInv=inv3(Tw);if(!TwInv)return null;
 return mat3mul(mat3mul(TwInv,Hn),Ti);}
function applyH(H,x,y){const w=H[2][0]*x+H[2][1]*y+H[2][2];
 return [(H[0][0]*x+H[0][1]*y+H[0][2])/w,(H[1][0]*x+H[1][1]*y+H[1][2])/w,w];}
function predictLen(p1,p2){
 const H=computeH();if(!H)return null;
 const u1=undistP(p1),u2=undistP(p2);if(!u1||!u2)return null;
 const w1=applyH(H,u1[0],u1[1]),w2=applyH(H,u2[0],u2[1]);
 return Math.hypot(w2[0]-w1[0],w2[1]-w1[1]);}

function draw(){
 if(!img.src)return;
 ctx.drawImage(img,0,0);
 if(curPts.length){ctx.strokeStyle='#e879f9';ctx.lineWidth=2;ctx.beginPath();
  ctx.moveTo(curPts[0].x,curPts[0].y);
  if(curPts[1])ctx.lineTo(curPts[1].x,curPts[1].y);ctx.stroke();
  curPts.forEach(p=>{ctx.fillStyle='#e879f9';ctx.beginPath();
   ctx.arc(p.x,p.y,4,0,7);ctx.fill();});}
}
cv.onclick=e=>{const r=cv.getBoundingClientRect();
 const sx=cv.width/r.width,sy=cv.height/r.height;
 if(curPts.length>=2)curPts=[];
 curPts.push({x:(e.clientX-r.left)*sx,y:(e.clientY-r.top)*sy});draw();};

function errClass(e){if(e===null)return'';
 const a=Math.abs(e);return a<2?'errgood':(a<8?'errmid':'errbad');}
function renderRefs(){
 document.querySelector('#refTbl tbody').innerHTML=refs.map((r,i)=>{
  const pl=predictLen(r.p1,r.p2);
  const err=pl!==null?(100*(pl-r.length)/r.length):null;
  return `<tr><td>${r.length.toFixed(2)} m</td>`
   +`<td>${pl!==null?pl.toFixed(2)+' m':'-'}</td>`
   +`<td class="${errClass(err)}">${err!==null?err.toFixed(1)+'%':'-'}</td>`
   +`<td><a href="#" onclick="refs.splice(${i},1);renderRefs();return false"
      style="color:var(--bad)">&#10005;</a></td></tr>`;
 }).join('');
}
function addRef(){
 if(curPts.length!==2){msgR.textContent='erst 2 Punkte klicken';return;}
 const L=num(refLen.value);
 if(isNaN(L)||L<=0){msgR.textContent='gueltige Laenge eingeben';return;}
 refs.push({p1:[curPts[0].x,curPts[0].y],p2:[curPts[1].x,curPts[1].y],length:L});
 curPts=[];refLen.value='';msgR.textContent='';draw();renderRefs();
}

function renderPtList(){
 document.getElementById('ptlist').innerHTML=calib.image_points.map((p,i)=>
  `<div class=ptrow><label><input type=checkbox ${fixedMask[i]?'checked':''}
    onchange="fixedMask[${i}]=this.checked"> vermessen/fix</label>
   <span>Punkt ${i+1}: (${calib.world_points[i][0]}, ${calib.world_points[i][1]}) m</span></div>`
 ).join('');
}

async function loadGallery(){
 const ev=await (await fetch('/api/events?limit=30')).json();
 const withRaw=ev.filter(e=>e.snapshot_raw||e.snapshot);
 document.getElementById('gallery').innerHTML=withRaw.map((e,i)=>
  `<img src="/snap/${e.snapshot_raw||e.snapshot}" data-src="/snap/${e.snapshot_raw||e.snapshot}"
    onclick="selectImg(this)">`).join('');
}
function selectImg(el){
 document.querySelectorAll('.gallery img').forEach(x=>x.classList.remove('sel'));
 el.classList.add('sel');
 curPts=[];img.src=el.dataset.src;
}
async function loadCalib(){
 const c=await (await fetch('/api/calibration')).json();
 calib.image_points=c.image_points||[];
 calib.world_points=c.world_points||[];
 calib.distortion=c.distortion||null;
 fixedMask=calib.image_points.map(()=>true);
 renderPtList();renderRefs();
 if(!calib.image_points.length)
  msgR.textContent='keine Kalibrierung gefunden - erst unter "Kalibrierung" anlegen';
}
async function doRefine(){
 if(!refs.length){msgR.textContent='mind. eine Referenz hinzufuegen';return;}
 msgR.textContent='rechne...';
 const r=await fetch('/api/refine',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({image_points:calib.image_points,
   world_points:calib.world_points,fixed:fixedMask,
   references:refs,distortion:calib.distortion})});
 const j=await r.json();
 if(!j.ok){msgR.textContent='Fehler: '+j.error;return;}
 msgR.textContent=(j.warn||'fertig');
 window._proposal=j.world_points;
 document.querySelector('#resTbl tbody').innerHTML=j.report.map(r=>
  `<tr><td>${r.length.toFixed(2)} m</td><td>${r.predicted??'-'}</td>`
  +`<td class="${errClass(r.error_pct)}">${r.error_pct??'-'}%</td></tr>`).join('');
 document.getElementById('resultBox').style.display='';
}
async function apply(){
 if(!window._proposal)return;
 const r=await fetch('/api/calibration',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({image_points:calib.image_points,
   world_points:window._proposal})});
 const j=await r.json();
 msgR.textContent=j.ok?'gespeichert & aktiv':'Fehler: '+j.error;
 if(j.ok){await loadCalib();document.getElementById('resultBox').style.display='none';}
}
loadGallery();loadCalib();
</script></body></html>
"""

EVENTS_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Alle Messungen</title><style>""" + BASE_CSS + """
 .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:0 0 14px}
 @media(max-width:900px){.kpis{grid-template-columns:repeat(3,1fr)}}
 .kpi{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:8px 12px}
 .kpi b{font-size:18px;display:block}
 .kpi span{font-size:11px;color:var(--mut)}
 .filters{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:14px}
 .filters>div{min-width:120px}
 select,input[type=date]{background:var(--bg);color:var(--txt);
  border:1px solid var(--line);border-radius:8px;padding:8px;width:100%}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{color:var(--mut);font-weight:500;text-align:left}
 th,td{padding:7px 8px;border-bottom:1px solid var(--line)}
 td img{height:44px;border-radius:6px;cursor:pointer;display:block}
 tr:hover td{background:var(--card2)}
 .speed{font-weight:700}.fast{color:var(--bad)}.mid{color:var(--warn)}.slow{color:var(--ok)}
 .pager{display:flex;gap:10px;align-items:center;margin-top:10px;color:var(--mut);font-size:13px}
__VIEWER_CSS__
 .danger{background:var(--card2);color:var(--bad)}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__</header>
<div style="padding:18px;max-width:1300px;margin:0 auto">
 <div class=card style="margin-bottom:16px">
  <div class=filters>
   <div><label>von</label><input type=date id=fFrom></div>
   <div><label>bis</label><input type=date id=fTo></div>
   <div><label>min. km/h</label><input type=number id=fMin step=1></div>
   <div><label>max. km/h</label><input type=number id=fMax step=1></div>
   <div><label>Richtung</label><select id=fDir>
    <option value="">beide</option>
    <option value="links->rechts">&#8594; links nach rechts</option>
    <option value="rechts->links">&#8592; rechts nach links</option>
   </select></div>
   <div><label>Klasse</label><select id=fKl>
    <option value="">alle</option>
    <option value="PKW">PKW</option>
    <option value="LKW">LKW</option>
    <option value="Bus">Bus</option>
    <option value="Motorrad">Motorrad</option>
    <option value="Fahrrad">Fahrrad</option>
    <option value="Fussgaenger">Fussgaenger</option>
    <option value="Sonstige">Sonstige</option>
    <option value="Fahrzeug">unklassifiziert</option>
   </select></div>
   <div><button onclick="offset=0;load()">Filtern</button></div>
   <div><button class=danger onclick="resetF()">zur&uuml;cksetzen</button></div>
   <div style="flex:1"></div>
   <div><button class=danger onclick="delFiltered()">gefilterte l&ouml;schen</button></div>
  </div>
  <div class=kpis>
   <div class=kpi><b id=kN>-</b><span>Treffer</span></div>
   <div class=kpi><b id=kAvg>-</b><span>&Oslash; km/h</span></div>
   <div class=kpi><b id=kMed>-</b><span>Median</span></div>
   <div class=kpi><b id=kV85>-</b><span>V85</span></div>
   <div class=kpi><b id=kMax>-</b><span>max km/h</span></div>
   <div class=kpi><b id=kLim>-</b><span id=kLimLbl>&gt; Limit</span></div>
  </div>
 </div>
 <details class=card id=statsBox style="margin-bottom:16px">
  <summary style="cursor:pointer;color:var(--mut);font-size:13px;
   text-transform:uppercase;letter-spacing:.4px">Diagramme zu den
   gefilterten Ergebnissen ein-/ausklappen</summary>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:12px"
   id=chartGrid>
   <div><h3>Geschwindigkeitsverteilung (km/h)</h3><canvas id=cHist></canvas>
    <div style="font-size:13px;color:var(--mut);margin-top:6px" id=dirInfo></div></div>
   <div><h3>Fahrzeuge je Stunde</h3><canvas id=cHourN></canvas></div>
   <div><h3>&Oslash; km/h je Stunde</h3><canvas id=cHourV></canvas></div>
   <div><h3>Letzte 14 Tage</h3><canvas id=cDays></canvas></div>
  </div>
 </details>
 <div class=card>
  <table><thead><tr><th>Bild</th><th>Zeit</th><th>km/h</th><th></th>
   <th>Klasse</th><th>Strecke</th><th>Dauer</th><th></th></tr></thead>
   <tbody id=tb></tbody></table>
  <div class=pager>
   <button onclick="page(-1)" style="background:var(--card2)">&larr; zur&uuml;ck</button>
   <span id=pinfo></span>
   <button onclick="page(1)" style="background:var(--card2)">weiter &rarr;</button>
  </div>
 </div>
</div>
__VIEWER_HTML__
<script>
let offset=0,limit=100,total=0,lastCharts=null,lastKpi=null;
let tip=null;
function ensureTip(){if(tip)return;
 tip=document.createElement('div');
 tip.style.cssText='position:fixed;pointer-events:none;display:none;'
  +'background:#1a2030;border:1px solid #232a3d;padding:5px 9px;'
  +'border-radius:7px;font-size:12px;color:#e8eaf2;z-index:30;'
  +'box-shadow:0 4px 14px rgba(0,0,0,.4)';
 document.body.appendChild(tip);}
function bars(id,labels,vals,opts){
 opts=opts||{};ensureTip();
 const c=document.getElementById(id),dpr=window.devicePixelRatio||1;
 const W=c.clientWidth,H=180;
 if(!W)return;
 c.style.height=H+'px';
 c.width=W*dpr;c.height=H*dpr;
 const x=c.getContext('2d');x.scale(dpr,dpr);
 const padL=30,padB=20,padT=12;
 const iw=W-padL-6,ih=H-padT-padB;
 const mx=Math.max(...vals,opts.hline||0,1);
 x.strokeStyle='#232a3d';x.beginPath();
 x.moveTo(padL,padT+ih);x.lineTo(padL+iw,padT+ih);x.stroke();
 const bw=iw/vals.length;
 x.fillStyle=opts.color||'#4f8ef7';
 vals.forEach((v,i)=>{const h=v/mx*ih;
  x.fillRect(padL+i*bw+1,padT+ih-h,Math.max(bw-2,1),h);});
 x.fillStyle='#8b93ab';x.font='10px sans-serif';
 const step=Math.ceil(labels.length/12);
 labels.forEach((l,i)=>{if(i%step)return;
  x.fillText(l,padL+i*bw,padT+ih+13);});
 x.textAlign='right';
 x.fillText(String(Math.round(mx)),padL-4,padT+8);
 x.fillText('0',padL-4,padT+ih);
 x.textAlign='left';
 if(opts.hline){const y=padT+ih-opts.hline/mx*ih;
  x.strokeStyle='#ff6b6b';x.setLineDash([4,4]);x.beginPath();
  x.moveTo(padL,y);x.lineTo(padL+iw,y);x.stroke();x.setLineDash([]);
  x.fillStyle='#ff6b6b';x.fillText(opts.hlineLabel||'',padL+4,y-4);}
 c._chart={padL,bw,n:vals.length,tip:opts.tip||((i)=>labels[i]+': '+vals[i])};
 if(!c._tipBound){c._tipBound=true;
  c.onmousemove=e=>{const ch=c._chart;if(!ch)return;
   const r=c.getBoundingClientRect();
   const px=(e.clientX-r.left)*(c.clientWidth/r.width);
   const i=Math.floor((px-ch.padL)/ch.bw);
   if(i<0||i>=ch.n){tip.style.display='none';return;}
   tip.textContent=ch.tip(i);
   tip.style.left=(e.clientX+14)+'px';
   tip.style.top=(e.clientY-30)+'px';
   tip.style.display='block';};
  c.onmouseleave=()=>{tip.style.display='none';};}
}
function renderCharts(){
 if(!lastCharts||!statsBox.open)return;
 const s=lastCharts,k=lastKpi;
 bars('cHist',s.bins.map(b=>b+''),s.hist,{color:'#4f8ef7',
  tip:i=>`${s.bins[i]}\u2013${s.bins[i]+5} km/h: ${s.hist[i]} Fahrzeuge`});
 bars('cHourN',[...Array(24).keys()].map(h=>h+''),s.hour_n,{color:'#3ddc84',
  tip:i=>`${i}:00\u2013${i+1}:00 Uhr: ${s.hour_n[i]} Fahrzeuge`});
 bars('cHourV',[...Array(24).keys()].map(h=>h+''),s.hour_avg,
  {color:'#ffb454',hline:k.limit,hlineLabel:k.limit+' km/h',
   tip:i=>`${i}:00\u2013${i+1}:00 Uhr: \u00d8 ${s.hour_avg[i]} km/h (${s.hour_n[i]} Fzg.)`});
 bars('cDays',s.days,s.day_n,{color:'#22d3ee',
  tip:i=>`${s.days[i]}: ${s.day_n[i]} Fahrzeuge, \u00d8 ${s.day_avg[i]||'-'} km/h`});
 dirInfo.innerHTML=s.richtung.map(r=>
  `${r.richtung==='links->rechts'?'&#8594;':'&#8592;'} ${r.n} Fzg., &Oslash; ${r.avg}, Median ${r.median} km/h`)
  .join(' &nbsp;&middot;&nbsp; ');
}
function spdClass(v){return v>=50?'fast':(v>=30?'mid':'slow');}
function dirArrow(d){return d==='links->rechts'?'&#8594;':'&#8592;';}
function qsFilters(){
 const p=new URLSearchParams();
 if(fFrom.value)p.set('from',fFrom.value);
 if(fTo.value)p.set('to',fTo.value);
 if(fMin.value)p.set('min_kmh',fMin.value);
 if(fMax.value)p.set('max_kmh',fMax.value);
 if(fDir.value)p.set('richtung',fDir.value);
 if(fKl.value)p.set('klasse',fKl.value);
 return p;}
async function load(){
 const p=qsFilters();p.set('limit',limit);p.set('offset',offset);
 const j=await (await fetch('/api/events/query?'+p)).json();
 total=j.total;
 const k=j.kpi;
 kN.textContent=k.anzahl;kAvg.textContent=k.avg;kMed.textContent=k.median;
 kV85.textContent=k.v85;kMax.textContent=k.max;
 kLim.textContent=k.ueber_limit_pct+' %';
 kLimLbl.textContent='> '+k.limit+' km/h';
 lastCharts=j.charts;lastKpi=k;renderCharts();
 lastEvents=j.events;
 tb.innerHTML=j.events.map((e,i)=>{
  const d=new Date(e.ts*1000).toLocaleString('de-DE');
  const img=e.snapshot?`<img src="/snap/${e.snapshot}"
    onclick="openEv(${i})">`:'';
  return `<tr><td>${img}</td><td>${d}</td>`
   +`<td class="speed ${spdClass(e.speed_kmh)}" title="${e.samples} Messpunkte${e.residual_m!=null?', Fit-Fehler '+e.residual_m+' m':''}">${e.speed_kmh.toFixed(1)}</td>`
   +`<td>${dirArrow(e.richtung)}</td>`
   +`<td>${e.klasse&&e.klasse!=='Fahrzeug'?e.klasse:'-'}</td>`
   +`<td>${e.distanz_m} m</td><td>${e.dauer_s} s</td>`
   +`<td><a href="#" onclick="delOne(${e.id});return false"
      style="color:var(--bad)" title="Messung l\\u00f6schen">&#10005;</a></td></tr>`;
 }).join('');
 const from=total?offset+1:0, to=Math.min(offset+limit,total);
 pinfo.textContent=`${from}\\u2013${to} von ${total}`;
}
function page(d){const no=offset+d*limit;
 if(no<0||no>=total)return;offset=no;load();}
function resetF(){fFrom.value='';fTo.value='';fMin.value='';fMax.value='';
 fDir.value='';fKl.value='';offset=0;load();}
async function delOne(id){
 await fetch('/api/events/'+id,{method:'DELETE'});load();}
async function delFiltered(){
 if(!total){alert('keine Treffer');return;}
 if(!confirm(`Wirklich ALLE ${total} gefilterten Messungen samt Snapshots l\\u00f6schen?`))return;
 const p=qsFilters();
 const j=await (await fetch('/api/events/query?'+p,{method:'DELETE'})).json();
 alert(j.deleted+' Messungen geloescht');offset=0;load();}
__VIEWER_JS__
statsBox.addEventListener('toggle',renderCharts);
window.addEventListener('resize',renderCharts);
load();
</script></body></html>
"""

SYSTEM_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>System</title><style>""" + BASE_CSS + """
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:18px}
 @media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}}
 .kpi{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
 .kpi b{font-size:19px;display:block}
 .kpi span{font-size:11px;color:var(--mut)}
 .bar{height:10px;background:var(--card2);border:1px solid var(--line);
  border-radius:6px;overflow:hidden;margin-top:8px}
 .bar>div{height:100%;background:var(--acc)}
 .hint{color:var(--mut);font-size:13px;line-height:1.5;max-width:600px}
 .danger{background:var(--card2);color:var(--bad)}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__</header>
<div class=wrap>
 <div class=card>
  <h3>Datenbestand</h3>
  <div class=kpis>
   <div class=kpi><b id=iN>-</b><span>Messungen</span></div>
   <div class=kpi><b id=iOld>-</b><span>&auml;lteste</span></div>
   <div class=kpi><b id=iNew>-</b><span>neueste</span></div>
   <div class=kpi><b id=iSnapN>-</b><span>Snapshots</span></div>
  </div>
  <h3>Belegter Platz</h3>
  <div class=kpis>
   <div class=kpi><b id=iDb>-</b><span>Datenbank</span></div>
   <div class=kpi><b id=iCsv>-</b><span>CSV</span></div>
   <div class=kpi><b id=iSnap>-</b><span>Snapshots</span></div>
   <div class=kpi><b id=iSum>-</b><span>TrafficCam gesamt</span></div>
  </div>
  <h3>Datentr&auml;ger</h3>
  <p style="margin:6px 0" id=iDisk>-</p>
  <div class=bar><div id=iDiskBar style="width:0%"></div></div>
 </div>
 <div class=card>
  <h3>Aufr&auml;umen</h3>
  <p class=hint>Automatische Aufbewahrung: Messungen (inkl. Snapshots), die
   &auml;lter sind als die eingestellte Frist, werden st&uuml;ndlich
   automatisch gel&ouml;scht. <b>0 = nie l&ouml;schen.</b> Die CSV-Datei
   w&auml;chst unabh&auml;ngig davon als fortlaufendes Protokoll weiter.</p>
  <p><label>Aufbewahrung (Tage)</label><br>
   <input type=number id=pDays step=1 min=0 style="width:120px">
   <button onclick="saveRetention()">Speichern</button>
   <span id=msgP class=save-msg></span></p>
  <h3 style="margin-top:18px">Manuell</h3>
  <p><input type=number id=mDays step=1 min=1 value=90 style="width:120px">
   <button class=danger onclick="purgeNow()">Messungen &auml;lter als X Tage
    jetzt l&ouml;schen</button>
   <span id=msgM class=save-msg></span></p>
 </div>
 <div class=card style="grid-column:1/-1">
  <h3>KI-Benchmark (Entscheidungshilfe: einfache vs. erweiterte Erfassung)</h3>
  <p class=hint>Misst, wie schnell die YOLO-Objekterkennung auf dieser
   Maschine l&auml;uft &mdash; <b>w&auml;hrend die normale Erkennung
   weiterl&auml;uft</b>, die Werte entstehen also unter realer Last.
   Getestet werden Vollbild und (falls definiert) der
   Messbereich-Ausschnitt. Ben&ouml;tigt das ultralytics-Paket wie die
   Snapshot-Klassifizierung; Dauer ca. 30&ndash;60&nbsp;Sekunden.</p>
  <p><button id=bStart onclick="startBench()">Benchmark starten</button>
   <span id=bMsg class=save-msg></span></p>
  <p id=bProg class=hint style="display:none"></p>
  <table id=bTab style="display:none;margin-top:8px"><thead>
   <tr><th>Variante</th><th>Bild</th><th>Netz</th><th>ms/Bild</th>
    <th>FPS</th><th>Einordnung</th></tr></thead>
   <tbody id=bBody></tbody></table>
  <p id=bLoad class=hint style="display:none"></p>
 </div>
</div>
<script>
let bTimer=null;
async function startBench(){
 const r=await fetch('/api/benchmark',{method:'POST'});
 const j=await r.json();
 if(!j.ok){bMsg.textContent=j.error;setTimeout(()=>bMsg.textContent='',6000);return;}
 bStart.disabled=true;pollBench();
 bTimer=setInterval(pollBench,1500);
}
async function pollBench(){
 const s=await (await fetch('/api/benchmark')).json();
 bProg.style.display=s.state==='running'?'block':'none';
 bProg.textContent=s.progress||'l\u00e4uft \u2026';
 if(s.results&&s.results.length){
  bTab.style.display='table';
  bBody.innerHTML=s.results.map(r=>
   `<tr><td>${r.variante}</td><td>${r.bild}</td><td>${r.imgsz}</td>`+
   `<td>${r.ms}</td><td><b>${r.fps}</b></td><td>${r.einordnung}</td></tr>`).join('');
 }
 if(s.load_s!==null&&s.load_s!==undefined){
  bLoad.style.display='block';
  bLoad.textContent=`Modell-Lade-/Warmlaufzeit: ${s.load_s} s (f\u00e4llt nur beim Start an)`;
 }
 if(s.state==='error'){
  bMsg.textContent=s.error;bStart.disabled=false;
  if(bTimer){clearInterval(bTimer);bTimer=null;}
 }
 if(s.state==='done'){
  bStart.disabled=false;
  if(bTimer){clearInterval(bTimer);bTimer=null;}
 }
}
pollBench();
function fmtB(b){if(b>=1e9)return (b/1e9).toFixed(2)+' GB';
 if(b>=1e6)return (b/1e6).toFixed(1)+' MB';
 if(b>=1e3)return (b/1e3).toFixed(0)+' kB';return b+' B';}
function fmtD(ts){return ts?new Date(ts*1000).toLocaleDateString('de-DE'):'-';}
async function load(){
 const s=await (await fetch('/api/system')).json();
 iN.textContent=s.events;
 iOld.textContent=fmtD(s.oldest_ts);iNew.textContent=fmtD(s.newest_ts);
 iSnapN.textContent=s.snapshot_count;
 iDb.textContent=fmtB(s.db_bytes);iCsv.textContent=fmtB(s.csv_bytes);
 iSnap.textContent=fmtB(s.snapshot_bytes);
 iSum.textContent=fmtB(s.db_bytes+s.csv_bytes+s.snapshot_bytes);
 const d=s.disk, pct=d.total?100*d.used/d.total:0;
 iDisk.textContent=`${fmtB(d.used)} von ${fmtB(d.total)} belegt \u00b7 `
  +`${fmtB(d.free)} frei (${pct.toFixed(0)}%)`;
 iDiskBar.style.width=pct.toFixed(0)+'%';
 iDiskBar.style.background=pct>90?'var(--bad)':(pct>75?'var(--warn)':'var(--acc)');
 pDays.value=s.aufbewahrung_tage;
}
async function saveRetention(){
 const r=await fetch('/api/settings',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({aufbewahrung_tage:parseFloat(pDays.value)||0})});
 msgP.textContent=(await r.json()).ok?'gespeichert':'Fehler';
}
async function purgeNow(){
 const d=parseInt(mDays.value);
 if(!d||d<1){msgM.textContent='Tage angeben';return;}
 const cut=new Date(Date.now()-d*86400000);
 const iso=cut.toISOString().slice(0,10);
 if(!confirm(`Wirklich alle Messungen vor dem ${cut.toLocaleDateString('de-DE')} `
  +`inkl. Snapshots l\u00f6schen?`))return;
 const j=await (await fetch('/api/events/query?to='+iso,{method:'DELETE'})).json();
 msgM.textContent=j.deleted+' geloescht';load();
}
load();
</script></body></html>
"""

SETTINGS_PAGE_HTML = """
<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Einstellungen</title><style>""" + BASE_CSS + """
 .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
 .save-msg{margin-left:10px;font-size:13px;color:var(--ok)}
</style></head><body>
<header><h1>TrafficCam</h1>
 __NAV__</header>
<div style="padding:18px;max-width:760px;margin:0 auto">
  <div class=card style="margin-bottom:18px">
   <h3>Sprache / Language</h3>
   <p style="margin:0"><select id=sLang onchange="saveLang()">
     <option value="de">Deutsch</option>
     <option value="en">English</option>
    </select> <span id=lMsg class=save-msg></span></p>
  </div>
  <div class=card style="margin-bottom:18px">
   <h3>Filter</h3>
   <div class=grid3>
    <div><label>min. km/h</label><input id=fMin type=number step=1></div>
    <div><label>max. km/h</label><input id=fMax type=number step=1></div>
    <div><label>Tempolimit</label><input id=fLim type=number step=5></div>
   </div>
   <h3 style="margin-top:16px">Zeitsteuerung</h3>
   <div class=grid3>
    <div><label>Modus</label>
     <select id=tMode style="width:100%;background:var(--bg);color:var(--txt);
      border:1px solid var(--line);border-radius:8px;padding:8px">
      <option value=immer>immer aktiv</option>
      <option value=zeit>Zeitfenster</option>
      <option value=sonne>Sonnenstand</option></select></div>
    <div><label>aktiv von</label><input id=tVon type=time></div>
    <div><label>aktiv bis</label><input id=tBis type=time></div>
   </div>
   <div class=grid3 style="margin-top:8px">
    <div><label>Breitengrad</label><input id=tLat type=number step=0.0001></div>
    <div><label>L&auml;ngengrad</label><input id=tLon type=number step=0.0001></div>
    <div><label>D&auml;mmerung +min</label><input id=tOff type=number step=5></div>
   </div>
   <p style="margin:12px 0 0"><button onclick="saveSettings()">Speichern</button>
    <span id=fMsg class=save-msg></span></p>
   <p style="font-size:12px;color:var(--mut);margin:10px 0 0">Wirkt sofort.
    Zeitfenster darf &uuml;ber Mitternacht gehen. Sonnenstand nutzt
    Breiten-/L&auml;ngengrad, Offset verl&auml;ngert die aktive Zeit in die
    D&auml;mmerung.</p>
  </div>

 <div class=card style="margin-top:18px">
  <h3>Erkennung (Experten)</h3>
  <p style="font-size:12px;color:var(--mut);margin:0 0 12px">Wird ohne
   Neustart &uuml;bernommen &mdash; der Hintergrund lernt danach ~10&nbsp;s
   neu an. Werte landen in der config.yaml (Kommentare dort gehen beim
   Speichern verloren; Referenz ist config.example.yaml).</p>
  <div class=grid3>
   <div><label title="hoeher = unempfindlicher gegen Rauschen/Flimmern">
    Empfindlichkeit (var_threshold)</label>
    <input id=dVar type=number step=1></div>
   <div><label title="kleiner = auch harte/dunkle Schatten werden ignoriert">
    Schatten-Schwelle (0..1)</label>
    <input id=dShadow type=number step=0.05></div>
   <div><label title="hoeher = Box-Unterkante klebt fester am Fahrzeug">
    Zeilen-F&uuml;llgrad (0..1)</label>
    <input id=dFill type=number step=0.05></div>
  </div>
  <div class=grid3 style="margin-top:8px">
   <div><label title="kleinere Bewegungen werden ignoriert">
    min. Blob-Fl&auml;che (px)</label>
    <input id=dArea type=number step=10></div>
   <div><label title="nahe Blobs zu einem Fahrzeug zusammenfassen">
    Merge-Abstand (px)</label>
    <input id=dGap type=number step=1></div>
   <div><label title="max. Fit-Restfehler; drueber gilt als Track-Geist">
    max. Restfehler (m)</label>
    <input id=dRes type=number step=0.05></div>
  </div>
  <p style="margin:14px 0 0"><label>Erfassung
   <select id=dMode style="margin-left:8px">
    <option value="einfach">einfach (Bewegungserkennung)</option>
    <option value="erweitert">erweitert (KI-Hybrid, ben&ouml;tigt ultralytics)</option>
   </select></label>
   <span class=hint style="display:block;font-size:12px;color:var(--mut);
    margin-top:4px">Erweitert: MOG2 trackt in Echtzeit, YOLO liefert
    zus&auml;tzlich beleuchtungsunabh&auml;ngige Fahrzeug-Anker auf dem
    Messbereich-Ausschnitt; die Messung nutzt bevorzugt die Anker.
    Entscheidungshilfe: KI-Benchmark auf der System-Seite. Wirkt ohne
    Neustart; ohne ultralytics l&auml;uft automatisch die einfache
    Erfassung.</span></p>
  <p style="margin:14px 0 0"><label style="cursor:pointer">
   <input type=checkbox id=dClassify> Snapshot-Klassifizierung
   (PKW/LKW/Fahrrad/...)</label></p>
  <p style="margin:10px 0 0"><label style="cursor:pointer"
    title="Rund um Sonnenauf-/untergang automatisch auf empfindlichere
Daemmerungs-Werte umschalten (empfindlicher, Schatten-Verwerfung aus,
niedriger Fuellgrad) - dunkle Reifen verschmelzen sonst mit der Fahrbahn">
   <input type=checkbox id=dDusk> D&auml;mmerungs-Profil (automatisch per
   Sonnenstand)</label></p>
  <p style="margin:10px 0 0"><label style="cursor:pointer"
    title="Tiefe Nacht (IR-Schwarzweissbild): unempfindlichere Werte, damit
Scheinwerferkegel und Streulicht nicht als Fahrzeuge zaehlen. Greift ab
~45min nach Sonnenuntergang; dazwischen gilt das Daemmerungs-Profil">
   <input type=checkbox id=dNight> Nacht-Profil (IR-Modus, gegen
   Scheinwerfer-Streulicht)</label></p>
  <p style="font-size:12px;color:var(--mut);margin:4px 0 0">Ben&ouml;tigt
   einmalig <code>ultralytics</code> in der venv (siehe README). Wird sofort
   aktiv; klassifiziert werden neue Ereignisse. Ob es l&auml;uft, zeigt das
   Dienst-Log beim n&auml;chsten Ereignis.</p>
  <p style="margin:12px 0 0"><button onclick="saveDetection()">Speichern</button>
   <span id=dMsg class=save-msg></span></p>
  <details style="margin-top:14px">
   <summary style="cursor:pointer;color:var(--acc);font-size:13px">Was
    bedeuten diese Werte? (mit Beispielen)</summary>
   <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
    gap:16px;margin-top:14px;font-size:13px;line-height:1.5">

    <div>
     <svg viewBox="0 0 300 90" style="width:100%;background:var(--card2);border-radius:8px">
      <rect x="30" y="30" width="70" height="34" fill="none" stroke="#ffb454" stroke-width="2"/>
      <circle cx="18" cy="20" r="2.5" fill="#ff6b6b"/><circle cx="120" cy="14" r="2.5" fill="#ff6b6b"/>
      <circle cx="15" cy="70" r="2.5" fill="#ff6b6b"/><circle cx="115" cy="78" r="2.5" fill="#ff6b6b"/>
      <circle cx="70" cy="12" r="2.5" fill="#ff6b6b"/><circle cx="130" cy="50" r="2.5" fill="#ff6b6b"/>
      <text x="72" y="86" fill="#8b93ab" font-size="10" text-anchor="middle">zu niedrig: Rauschen wird erkannt</text>
      <line x1="150" y1="8" x2="150" y2="82" stroke="#232a3d"/>
      <rect x="195" y="30" width="70" height="34" fill="none" stroke="#3ddc84" stroke-width="2"/>
      <text x="228" y="86" fill="#8b93ab" font-size="10" text-anchor="middle">passend: nur das Fahrzeug</text>
     </svg>
     <b>Empfindlichkeit (var_threshold)</b> &mdash; wie stark sich ein Pixel
     vom gelernten Hintergrund unterscheiden muss, um als Bewegung zu gelten.
     <b>Symptom:</b> Regen, Bl&auml;tterrauschen oder Flimmern erzeugen
     Mini-Boxen &rarr; erh&ouml;hen (40&ndash;60). Fahrzeuge zerfallen in der
     D&auml;mmerung oder fehlen &rarr; senken (20&ndash;28). Standard 32.
    </div>

    <div>
     <svg viewBox="0 0 300 90" style="width:100%;background:var(--card2);border-radius:8px">
      <rect x="20" y="22" width="60" height="28" rx="6" fill="#4f8ef7"/>
      <ellipse cx="80" cy="58" rx="45" ry="9" fill="#000" opacity="0.55"/>
      <rect x="14" y="16" width="118" height="52" fill="none" stroke="#ff6b6b" stroke-width="2" stroke-dasharray="4 3"/>
      <text x="72" y="86" fill="#8b93ab" font-size="10" text-anchor="middle">Schatten wird Teil der Box</text>
      <line x1="150" y1="8" x2="150" y2="82" stroke="#232a3d"/>
      <rect x="180" y="22" width="60" height="28" rx="6" fill="#4f8ef7"/>
      <ellipse cx="240" cy="58" rx="45" ry="9" fill="#000" opacity="0.25"/>
      <rect x="176" y="18" width="68" height="36" fill="none" stroke="#3ddc84" stroke-width="2"/>
      <text x="228" y="86" fill="#8b93ab" font-size="10" text-anchor="middle">Schatten wird ignoriert</text>
     </svg>
     <b>Schatten-Schwelle</b> &mdash; wie dunkel ein Bereich gegen&uuml;ber
     dem Hintergrund sein darf und trotzdem noch als Schatten (statt Objekt)
     durchgeht. <b>Kleiner = mehr wird als Schatten verworfen.</b>
     <b>Symptom:</b> Box frisst den Schattenwurf bei tiefer Sonne &rarr;
     senken (0,2). Dunkle Fahrzeuge zerfallen oder verschwinden teilweise
     &rarr; erh&ouml;hen (0,4). Standard 0,3.
    </div>

    <div>
     <svg viewBox="0 0 300 90" style="width:100%;background:var(--card2);border-radius:8px">
      <rect x="30" y="18" width="80" height="30" rx="6" fill="#4f8ef7"/>
      <circle cx="45" cy="50" r="6" fill="#4f8ef7"/><circle cx="95" cy="50" r="6" fill="#4f8ef7"/>
      <rect x="40" y="58" width="20" height="5" fill="#4f8ef7" opacity="0.5"/>
      <rect x="26" y="14" width="90" height="56" fill="none" stroke="#ff6b6b" stroke-width="2" stroke-dasharray="4 3"/>
      <circle cx="70" cy="66" r="3" fill="#ffb454"/>
      <text x="72" y="86" fill="#8b93ab" font-size="10" text-anchor="middle">Auslaeufer zieht Messpunkt runter</text>
      <line x1="150" y1="8" x2="150" y2="82" stroke="#232a3d"/>
      <rect x="185" y="18" width="80" height="30" rx="6" fill="#4f8ef7"/>
      <circle cx="200" cy="50" r="6" fill="#4f8ef7"/><circle cx="250" cy="50" r="6" fill="#4f8ef7"/>
      <rect x="181" y="14" width="90" height="45" fill="none" stroke="#3ddc84" stroke-width="2"/>
      <circle cx="226" cy="57" r="3" fill="#3ddc84"/>
      <text x="228" y="86" fill="#8b93ab" font-size="10" text-anchor="middle">Kante sitzt an den Raedern</text>
     </svg>
     <b>Zeilen-F&uuml;llgrad (tighten_min_fill)</b> &mdash; eine Bildzeile
     z&auml;hlt erst zur Box, wenn dieser Anteil der Boxbreite dort wirklich
     Bewegungspixel enth&auml;lt. Der Bodenmesspunkt sitzt an der Unterkante!
     <b>Symptom:</b> Unterkante h&auml;ngt unter den R&auml;dern (Maske-Haken
     zeigt d&uuml;nnes Band darunter) &rarr; erh&ouml;hen (0,25&ndash;0,35).
     R&auml;der werden abgeschnitten &rarr; senken. Standard 0,15.
    </div>

    <div>
     <svg viewBox="0 0 300 90" style="width:100%;background:var(--card2);border-radius:8px">
      <circle cx="45" cy="40" r="7" fill="#8b93ab"/>
      <text x="45" y="26" fill="#3ddc84" font-size="12" text-anchor="middle">&#10005;</text>
      <text x="45" y="66" fill="#8b93ab" font-size="10" text-anchor="middle">Vogel: zu klein</text>
      <rect x="85" y="26" width="50" height="26" fill="none" stroke="#3ddc84" stroke-width="2"/>
      <text x="110" y="66" fill="#8b93ab" font-size="10" text-anchor="middle">Auto: gross genug</text>
      <line x1="150" y1="8" x2="150" y2="82" stroke="#232a3d"/>
      <rect x="196" y="30" width="18" height="12" fill="none" stroke="#ff6b6b" stroke-width="1.5"/>
      <text x="205" y="60" fill="#8b93ab" font-size="10" text-anchor="middle">zu hoch: fernes</text>
      <text x="205" y="72" fill="#8b93ab" font-size="10" text-anchor="middle">Auto fehlt</text>
     </svg>
     <b>min. Blob-Fl&auml;che</b> &mdash; kleinere Bewegungen werden komplett
     ignoriert (Fl&auml;che in Pixeln der internen 640er-Analysebreite).
     <b>Symptom:</b> V&ouml;gel, Katzen oder wehende &Auml;ste erzeugen
     Messungen &rarr; erh&ouml;hen (500&ndash;800). Ferne/kleine Fahrzeuge
     werden nicht mehr erfasst &rarr; senken. Standard 350.
    </div>

    <div>
     <svg viewBox="0 0 300 90" style="width:100%;background:var(--card2);border-radius:8px">
      <rect x="22" y="28" width="34" height="24" fill="#4f8ef7"/>
      <rect x="66" y="28" width="44" height="24" fill="#4f8ef7"/>
      <rect x="18" y="24" width="98" height="34" fill="none" stroke="#3ddc84" stroke-width="2"/>
      <text x="68" y="76" fill="#8b93ab" font-size="10" text-anchor="middle">zerfallenes Auto &rarr; eine Box</text>
      <line x1="150" y1="8" x2="150" y2="82" stroke="#232a3d"/>
      <rect x="172" y="28" width="40" height="24" fill="#4f8ef7"/>
      <rect x="230" y="28" width="40" height="24" fill="#22d3ee"/>
      <rect x="168" y="24" width="106" height="34" fill="none" stroke="#ff6b6b" stroke-width="2" stroke-dasharray="4 3"/>
      <text x="222" y="76" fill="#8b93ab" font-size="10" text-anchor="middle">zu hoch: 2 Autos verschmelzen</text>
     </svg>
     <b>Merge-Abstand</b> &mdash; Bewegungs-Blobs, die n&auml;her als dieser
     Abstand liegen, gelten als ein Fahrzeug. <b>Symptom:</b> Ein Auto
     erscheint als zwei flackernde Boxen (Dachtr&auml;ger, Anh&auml;nger)
     &rarr; erh&ouml;hen. Zwei sich begegnende Fahrzeuge verschmelzen zu
     einer Box (erzeugt Track-Geister!) &rarr; senken. Standard 12.
    </div>

    <div>
     <svg viewBox="0 0 300 90" style="width:100%;background:var(--card2);border-radius:8px">
      <polyline points="20,45 45,44 70,46 95,45 120,44" fill="none" stroke="#3ddc84" stroke-width="2" stroke-dasharray="2 4"/>
      <text x="72" y="76" fill="#8b93ab" font-size="10" text-anchor="middle">saubere Spur: wird gespeichert</text>
      <line x1="150" y1="8" x2="150" y2="82" stroke="#232a3d"/>
      <polyline points="170,50 195,48 215,47 225,22 250,20 275,18" fill="none" stroke="#ff6b6b" stroke-width="2" stroke-dasharray="2 4"/>
      <text x="222" y="76" fill="#8b93ab" font-size="10" text-anchor="middle">Sprung (ID-Tausch): verworfen</text>
     </svg>
     <b>max. Restfehler</b> &mdash; wie weit die Messpunkte im Mittel von
     einer gleichm&auml;&szlig;igen Fahrt abweichen d&uuml;rfen (Meter).
     Track-Verwechslungen erzeugen Spr&uuml;nge im Pfad und damit
     Phantasie-Geschwindigkeiten &mdash; die fallen hier raus.
     <b>Symptom:</b> Immer noch &gt;100-km/h-Geister in der Liste &rarr;
     senken (0,4). Offensichtlich echte Fahrten fehlen trotz sauberer Spur
     &rarr; erh&ouml;hen (0,8&ndash;1,0). Standard 0,6.
    </div>

   </div>
  </details>
 </div>
</div>
<script>
async function saveLang(){
 await fetch('/api/settings',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({sprache:sLang.value})});
 location.reload();
}
async function loadDetection(){
 const d=await (await fetch('/api/detection')).json();
 dVar.value=d.var_threshold; dShadow.value=d.shadow_threshold;
 dFill.value=d.tighten_min_fill; dArea.value=d.min_area;
 dGap.value=d.merge_gap; dRes.value=d.max_residual_m;
 dClassify.checked=!!d.classify_snapshots;
 dMode.value=d.erfassung||'einfach';
 dDusk.checked=!!d.dusk_enabled;
 dNight.checked=!!d.nacht_enabled;
}
async function saveDetection(){
 const body={var_threshold:dVar.value,shadow_threshold:dShadow.value,
  tighten_min_fill:dFill.value,min_area:dArea.value,
  merge_gap:dGap.value,max_residual_m:dRes.value,
  classify_snapshots:dClassify.checked,dusk_enabled:dDusk.checked,
  erfassung:dMode.value,nacht_enabled:dNight.checked};
 const r=await fetch('/api/detection',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const j=await r.json();
 dMsg.textContent=j.ok?'\u00fcbernommen (ohne Neustart)':'Fehler: '+j.error;
 setTimeout(()=>dMsg.textContent='',4000);
}
loadDetection();
async function loadSettings(){
 const s=await (await fetch('/api/settings')).json();
 fMin.value=s.min_kmh; fMax.value=s.max_kmh; fLim.value=s.tempolimit_kmh;
 tMode.value=s.tracking_mode; tVon.value=s.aktiv_von; tBis.value=s.aktiv_bis;
 tLat.value=s.lat; tLon.value=s.lon; tOff.value=s.sonnen_offset_min;
 sLang.value=s.sprache||'de';
}
async function saveSettings(){
 const body={min_kmh:parseFloat(fMin.value),max_kmh:parseFloat(fMax.value),
  tempolimit_kmh:parseFloat(fLim.value),tracking_mode:tMode.value,
  aktiv_von:tVon.value,aktiv_bis:tBis.value,
  lat:parseFloat(tLat.value),lon:parseFloat(tLon.value),
  sonnen_offset_min:parseFloat(tOff.value)};
 const r=await fetch('/api/settings',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const j=await r.json();
 fMsg.textContent=j.ok?'gespeichert':'Fehler';
 setTimeout(()=>fMsg.textContent='',2500);
}
loadSettings();
</script></body></html>
"""


def _nav_html(cur):
    items = [("/", "Dashboard"), ("/messungen", "Messungen"),
             ("/statistik", "Statistik"), ("/calibrate", "Kalibrierung"),
             ("/einstellungen", "Einstellungen"), ("/system", "System")]
    return "<nav>" + "".join(
        '<a href="%s"%s>%s</a>' % (u, ' class=cur' if u == cur else '', t)
        for u, t in items) + "</nav>"


INDEX_HTML = INDEX_HTML.replace("__NAV__", _nav_html("/"))
EVENTS_HTML = EVENTS_HTML.replace("__NAV__", _nav_html("/messungen"))
STATS_HTML = STATS_HTML.replace("__NAV__", _nav_html("/statistik"))
CALIB_HTML = CALIB_HTML.replace("__NAV__", _nav_html("/calibrate"))
REFINE_HTML = REFINE_HTML.replace("__NAV__", _nav_html("/calibrate"))
SETTINGS_PAGE_HTML = SETTINGS_PAGE_HTML.replace("__NAV__",
                                                _nav_html("/einstellungen"))
SYSTEM_HTML = SYSTEM_HTML.replace("__NAV__", _nav_html("/system"))


VIEWER_HTML = '<div id=modal>\n <span id=mClose onclick="closeEv()">&#10005;</span>\n <button class=mnav onclick="stepEv(-1)">&#9664;</button>\n <div style="display:flex;flex-direction:column;gap:8px;align-items:center;min-width:0">\n  <canvas id=mCv></canvas>\n  <div id=mCap></div>\n  <div id=mHint>Klick ins Bild = Lineal (2 Punkte, 3. Klick setzt zur&uuml;ck)\n   &middot; &larr;/&rarr; bl&auml;ttern &middot; Esc schlie&szlig;en</div>\n </div>\n <button class=mnav onclick="stepEv(1)">&#9654;</button>\n</div>'
VIEWER_JS = "/* ---- Messungs-Viewer mit Blaettern + Lineal ---- */\nlet lastEvents=[],evIdx=-1,rPts=[],calibG=null;\nconst evImg=new Image();\nfunction undistP(p){const d=calibG&&calibG.distortion;if(!d)return p;\n const nx=(p[0]-d.cx)/d.scale,ny=(p[1]-d.cy)/d.scale;\n const den=1+d.lambda*(nx*nx+ny*ny);if(den<0.05)return null;\n const f=1/den;return [d.cx+d.scale*nx*f,d.cy+d.scale*ny*f];}\nfunction normT(P){const mx=P.reduce((s,p)=>s+p[0],0)/P.length,\n my=P.reduce((s,p)=>s+p[1],0)/P.length;\n const md=P.reduce((s,p)=>s+Math.hypot(p[0]-mx,p[1]-my),0)/P.length;\n const s=md>1e-9?Math.SQRT2/md:1;return [[s,0,-s*mx],[0,s,-s*my],[0,0,1]];}\nfunction mat3mul(A,B){const C=[[0,0,0],[0,0,0],[0,0,0]];\n for(let i=0;i<3;i++)for(let j=0;j<3;j++)for(let k=0;k<3;k++)C[i][j]+=A[i][k]*B[k][j];\n return C;}\nfunction inv3(m){const a=m[0][0],b=m[0][1],c=m[0][2],d=m[1][0],e=m[1][1],\n f=m[1][2],g=m[2][0],h=m[2][1],i=m[2][2];\n const A=e*i-f*h,B=c*h-b*i,C=b*f-c*e,D=f*g-d*i,E=a*i-c*g,F=c*d-a*f,\n G=d*h-e*g,Hh=b*g-a*h,I=a*e-b*d;\n const det=a*A+b*D+c*G;if(Math.abs(det)<1e-12)return null;\n return [[A/det,B/det,C/det],[D/det,E/det,F/det],[G/det,Hh/det,I/det]];}\nfunction computeHG(){\n if(!calibG||!calibG.image_points||calibG.image_points.length<4)return null;\n const pairs=calibG.image_points.map((p,i)=>({u:undistP(p),\n  w:calibG.world_points[i]})).filter(q=>q.u);\n if(pairs.length<4)return null;\n const Ti=normT(pairs.map(q=>q.u)),Tw=normT(pairs.map(q=>q.w));\n const nrm=(T,p)=>[T[0][0]*p[0]+T[0][2],T[1][1]*p[1]+T[1][2]];\n const A=[],b=[];\n for(let k=0;k<pairs.length;k++){\n  const [x,y]=nrm(Ti,pairs[k].u),[X,Y]=nrm(Tw,pairs[k].w);\n  A.push([x,y,1,0,0,0,-X*x,-X*y]);b.push(X);\n  A.push([0,0,0,x,y,1,-Y*x,-Y*y]);b.push(Y);}\n const n=8,M=Array.from({length:n},()=>new Array(n+1).fill(0));\n for(let r=0;r<A.length;r++)for(let i=0;i<n;i++){\n  for(let j=0;j<n;j++)M[i][j]+=A[r][i]*A[r][j];M[i][n]+=A[r][i]*b[r];}\n for(let i=0;i<n;i++){let piv=i;\n  for(let k=i+1;k<n;k++)if(Math.abs(M[k][i])>Math.abs(M[piv][i]))piv=k;\n  [M[i],M[piv]]=[M[piv],M[i]];if(Math.abs(M[i][i])<1e-12)return null;\n  for(let k=i+1;k<n;k++){const f=M[k][i]/M[i][i];\n   for(let j=i;j<=n;j++)M[k][j]-=f*M[i][j];}}\n const h=new Array(n);\n for(let i=n-1;i>=0;i--){let s=M[i][n];\n  for(let j=i+1;j<n;j++)s-=M[i][j]*h[j];h[i]=s/M[i][i];}\n const Hn=[[h[0],h[1],h[2]],[h[3],h[4],h[5]],[h[6],h[7],1]];\n const TwInv=inv3(Tw);if(!TwInv)return null;\n return mat3mul(mat3mul(TwInv,Hn),Ti);}\nfunction applyHG(H,x,y){const w=H[2][0]*x+H[2][1]*y+H[2][2];\n return [(H[0][0]*x+H[0][1]*y+H[0][2])/w,(H[1][0]*x+H[1][1]*y+H[1][2])/w];}\nfunction measureG(){\n if(rPts.length<2)return null;\n const H=computeHG();if(!H)return null;\n const u1=undistP(rPts[0]),u2=undistP(rPts[1]);\n if(!u1||!u2)return null;\n const w1=applyHG(H,u1[0],u1[1]),w2=applyHG(H,u2[0],u2[1]);\n return Math.hypot(w2[0]-w1[0],w2[1]-w1[1]);}\nasync function openEv(i){\n if(calibG===null){\n  try{calibG=await (await fetch('/api/calibration')).json()||{};}\n  catch(e){calibG={};}}\n evIdx=i;rPts=[];modal.style.display='flex';showEv();}\nfunction closeEv(){modal.style.display='none';}\nfunction stepEv(d){\n let i=evIdx+d;\n while(i>=0&&i<lastEvents.length&&!lastEvents[i].snapshot)i+=d;\n if(i<0||i>=lastEvents.length)return;\n evIdx=i;rPts=[];showEv();}\nfunction showEv(){\n const e=lastEvents[evIdx];if(!e)return;\n const dir=e.richtung==='links->rechts'?'\\u2192':'\\u2190';\n mCap.textContent=`${new Date(e.ts*1000).toLocaleString('de-DE')} \\u00b7 `\n  +`${e.speed_kmh.toFixed(1)} km/h ${dir}`\n  +`${e.klasse&&e.klasse!=='Fahrzeug'?' \\u00b7 '+e.klasse:''} \\u00b7 ${e.distanz_m} m / ${e.dauer_s} s`\n  +` \\u00b7 ${evIdx+1}/${lastEvents.length}`;\n evImg.onload=()=>{mCv.width=evImg.width;mCv.height=evImg.height;drawEv();};\n evImg.src='/snap/'+e.snapshot;}\nfunction drawEv(){\n const x=mCv.getContext('2d');\n x.drawImage(evImg,0,0);\n if(!rPts.length)return;\n x.strokeStyle='#e879f9';x.fillStyle='#e879f9';x.lineWidth=2;\n x.beginPath();x.moveTo(rPts[0][0],rPts[0][1]);\n if(rPts[1])x.lineTo(rPts[1][0],rPts[1][1]);x.stroke();\n rPts.forEach(p=>{x.beginPath();x.arc(p[0],p[1],4,0,7);x.fill();});\n if(rPts.length===2){\n  const d=measureG();\n  const mx=(rPts[0][0]+rPts[1][0])/2,my=(rPts[0][1]+rPts[1][1])/2;\n  const t=d!==null?d.toFixed(2)+' m':'keine Kalibrierung';\n  x.font='bold 16px sans-serif';x.lineWidth=4;x.strokeStyle='#000';\n  x.strokeText(t,mx+10,my-10);x.fillText(t,mx+10,my-10);}}\nmCv.onclick=e=>{\n const r=mCv.getBoundingClientRect();\n const sx=mCv.width/r.width,sy=mCv.height/r.height;\n if(rPts.length>=2)rPts=[];\n rPts.push([(e.clientX-r.left)*sx,(e.clientY-r.top)*sy]);drawEv();};\nmodal.onclick=e=>{if(e.target===modal)closeEv();};\ndocument.addEventListener('keydown',e=>{\n if(modal.style.display!=='flex')return;\n if(e.key==='ArrowLeft')stepEv(-1);\n else if(e.key==='ArrowRight')stepEv(1);\n else if(e.key==='Escape')closeEv();});\n"
VIEWER_CSS = ' #modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);\n  z-index:20;align-items:center;justify-content:center;padding:14px;gap:12px}\n #modal canvas{max-width:calc(96vw - 140px);max-height:78vh;\n  border-radius:12px;cursor:crosshair}\n @media(max-width:700px){ #modal canvas{max-width:96vw}}\n .mnav{background:rgba(26,32,48,.9);color:#fff;border:1px solid var(--line);\n  font-size:22px;padding:16px 12px;border-radius:10px;flex:0 0 auto}\n #mClose{position:absolute;top:14px;right:20px;color:#fff;font-size:28px;\n  cursor:pointer;z-index:21}\n #mCap{color:var(--txt);font-size:14px;text-align:center}\n #mHint{color:var(--mut);font-size:12px;text-align:center}'
VIEWER_HTML = VIEWER_HTML.replace(
    "<div id=mCap></div>",
    "<div id=mCap></div>\n"
    "  <button id=mDel onclick=\"delCurrent()\" "
    "style=\"background:var(--card2);color:var(--bad);"
    "border:1px solid var(--line);padding:6px 16px;border-radius:8px;"
    "cursor:pointer\">Messung l&ouml;schen</button>")

VIEWER_JS = VIEWER_JS + """
async function delCurrent(){
 const e=lastEvents[evIdx];if(!e)return;
 if(!confirm('Diese Messung samt Snapshot endgueltig loeschen?'))return;
 await fetch('/api/events/'+e.id,{method:'DELETE'});
 lastEvents.splice(evIdx,1);
 let i=evIdx;
 while(i<lastEvents.length&&!lastEvents[i].snapshot)i++;
 if(i>=lastEvents.length){i=evIdx-1;while(i>=0&&!lastEvents[i].snapshot)i--;}
 if(i<0||i>=lastEvents.length){closeEv();}
 else{evIdx=i;rPts=[];showEv();}
 if(typeof load==='function')load();
 else if(typeof tick==='function')tick();
}
document.addEventListener('keydown',e=>{
 if(modal.style.display!=='flex')return;
 if(e.key==='Delete')delCurrent();});
"""

# Diagnose-Plot + Swipe + mobile Blaetter-Buttons
VIEWER_HTML = VIEWER_HTML.replace(
    '<button id=mDel onclick="delCurrent()" ',
    '<canvas id=mPlot width=460 height=150 style="display:none;'
    'background:var(--card2);border-radius:10px;max-width:96vw"></canvas>\n'
    '  <div><button id=mDiag onclick="toggleDiag()" '
    'style="background:var(--card2);color:var(--acc);'
    'border:1px solid var(--line);padding:6px 16px;border-radius:8px;'
    'cursor:pointer;margin-right:8px">Diagnose</button>'
    '<button id=mDel onclick="delCurrent()" ')
VIEWER_HTML = VIEWER_HTML.replace(
    'cursor:pointer">Messung l&ouml;schen</button>',
    'cursor:pointer">Messung l&ouml;schen</button></div>')

VIEWER_CSS = VIEWER_CSS + """
 @media(max-width:700px){
  #modal .mnav{position:absolute;top:50%;transform:translateY(-50%);
   z-index:22;opacity:.88;padding:18px 10px}
  #modal .mnav:first-of-type{left:6px}
  #modal .mnav:last-of-type{right:6px}}"""

VIEWER_JS = VIEWER_JS + """
let diagOn=false;
function toggleDiag(){diagOn=!diagOn;drawDiag();}
function drawDiag(){
 mPlot.style.display=diagOn?'block':'none';
 if(!diagOn)return;
 const e=lastEvents[evIdx];if(!e)return;
 const x=mPlot.getContext('2d');
 x.clearRect(0,0,mPlot.width,mPlot.height);
 let P=null;
 try{P=typeof e.punkte==='string'?JSON.parse(e.punkte):e.punkte;}catch(_){}
 x.font='11px sans-serif';
 if(!P||!P.samples||P.samples.length<2){
  x.fillStyle='#8b93ab';
  x.fillText('keine Punktdaten (Messung vor dem Update)',14,80);return;}
 const all=P.samples.concat(P.anchors||[]);
 // Hauptachse (PCA) der Weltpunkte
 const mx=all.reduce((s,p)=>s+p[1],0)/all.length,
       my=all.reduce((s,p)=>s+p[2],0)/all.length;
 let sxx=0,sxy=0,syy=0;
 all.forEach(p=>{const dx=p[1]-mx,dy=p[2]-my;
  sxx+=dx*dx;sxy+=dx*dy;syy+=dy*dy;});
 const th=0.5*Math.atan2(2*sxy,sxx-syy),ax=Math.cos(th),ay=Math.sin(th);
 const proj=p=>({t:p[0],s:(p[1]-mx)*ax+(p[2]-my)*ay});
 const S=P.samples.map(proj),A=(P.anchors||[]).map(proj);
 const used=(e.erfassung==='erweitert'&&A.length>=3)?A:S;
 // Fit ueber die tatsaechlich genutzten Punkte
 const n=used.length;
 const st_=used.reduce((s,p)=>s+p.t,0)/n,ss=used.reduce((s,p)=>s+p.s,0)/n;
 let num=0,den=0;
 used.forEach(p=>{num+=(p.t-st_)*(p.s-ss);den+=(p.t-st_)*(p.t-st_);});
 const k=den>1e-9?num/den:0;
 const pts=S.concat(A);
 const t0=Math.min(...pts.map(p=>p.t)),t1=Math.max(...pts.map(p=>p.t));
 const s0=Math.min(...pts.map(p=>p.s)),s1=Math.max(...pts.map(p=>p.s));
 const W=mPlot.width,H=mPlot.height,padL=34,padB=18,padT=20;
 const X=t=>padL+(t-t0)/Math.max(t1-t0,1e-6)*(W-padL-10);
 const Y=s=>H-padB-(s-s0)/Math.max(s1-s0,1e-6)*(H-padT-padB);
 x.strokeStyle='#232a3d';
 x.strokeRect(padL,padT,W-padL-10,H-padT-padB);
 // Fit-Gerade
 x.strokeStyle='#3ddc84';x.lineWidth=2;x.beginPath();
 x.moveTo(X(t0),Y(ss+k*(t0-st_)));x.lineTo(X(t1),Y(ss+k*(t1-st_)));x.stroke();
 // MOG2-Punkte gelb, Anker cyan
 x.fillStyle='#ffd23f';
 S.forEach(p=>{x.beginPath();x.arc(X(p.t),Y(p.s),2.6,0,7);x.fill();});
 x.fillStyle='#22d3ee';
 A.forEach(p=>{x.beginPath();x.arc(X(p.t),Y(p.s),4.2,0,7);x.fill();});
 x.fillStyle='#e8eaf2';
 x.fillText(`Fit ${(Math.abs(k)*3.6).toFixed(1)} km/h (${
  e.erfassung==='erweitert'?'KI-Anker':'MOG2'})`,padL+6,14);
 x.fillStyle='#8b93ab';
 x.fillText('Position (m) \u00fcber Zeit (s) \u00b7 gelb=MOG2 \u00b7 cyan=KI-Anker',
  padL+6,H-4);
}
mCv.addEventListener('touchstart',e=>{
 if(e.touches.length===1)mCv._tx=e.touches[0].clientX;},{passive:true});
mCv.addEventListener('touchend',e=>{
 if(mCv._tx===undefined)return;
 const dx=e.changedTouches[0].clientX-mCv._tx;mCv._tx=undefined;
 if(Math.abs(dx)>45)stepEv(dx<0?1:-1);},{passive:true});
const _showEvOrig=showEv;
showEv=function(){_showEvOrig();drawDiag();};
"""

for _n in ("INDEX_HTML", "EVENTS_HTML"):
    globals()[_n] = (globals()[_n]
                     .replace("__VIEWER_HTML__", VIEWER_HTML)
                     .replace("__VIEWER_JS__", VIEWER_JS)
                     .replace("__VIEWER_CSS__", VIEWER_CSS))


from . import i18n as _i18n

INDEX_HTML_EN = _i18n.translate(INDEX_HTML)
EVENTS_HTML_EN = _i18n.translate(EVENTS_HTML)
STATS_HTML_EN = _i18n.translate(STATS_HTML)
CALIB_HTML_EN = _i18n.translate(CALIB_HTML)
REFINE_HTML_EN = _i18n.translate(REFINE_HTML)
SETTINGS_PAGE_HTML_EN = _i18n.translate(SETTINGS_PAGE_HTML)
SYSTEM_HTML_EN = _i18n.translate(SYSTEM_HTML)
