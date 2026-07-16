"""Persistenz: SQLite + CSV, annotierte Snapshots."""
from __future__ import annotations

import csv
import os
import sqlite3
import threading
import time

import cv2

CSV_HEADER = ["timestamp", "speed_kmh", "richtung", "laenge_m",
              "distanz_m", "dauer_s", "samples", "snapshot"]

import json


class Storage:
    def __init__(self, db_path, csv_path, save_snapshots, snapshot_dir):
        self.db_path = db_path
        self.csv_path = csv_path
        self.save_snapshots = save_snapshots
        self.snapshot_dir = snapshot_dir
        self._lock = threading.Lock()

        for p in (db_path, csv_path):
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
        os.makedirs(snapshot_dir, exist_ok=True)

        self._init_db()
        self._init_csv()

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS events (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL, klasse TEXT, speed_kmh REAL, richtung TEXT,
                   distanz_m REAL, dauer_s REAL, samples INTEGER, snapshot TEXT
               )"""
        )
        # Migration: Laenge-Spalte nachruesten, falls DB aus alter Version
        cols = [r[1] for r in con.execute("PRAGMA table_info(events)")]
        if "laenge_m" not in cols:
            con.execute("ALTER TABLE events ADD COLUMN laenge_m REAL DEFAULT 0")
        if "snapshot_raw" not in cols:
            con.execute("ALTER TABLE events ADD COLUMN snapshot_raw TEXT DEFAULT ''")
        if "bbox" not in cols:
            con.execute("ALTER TABLE events ADD COLUMN bbox TEXT DEFAULT ''")
        if "residual_m" not in cols:
            con.execute(
                "ALTER TABLE events ADD COLUMN residual_m REAL DEFAULT NULL")
        if "erfassung" not in cols:
            con.execute(
                "ALTER TABLE events ADD COLUMN erfassung TEXT DEFAULT ''")
        if "punkte" not in cols:
            con.execute(
                "ALTER TABLE events ADD COLUMN punkte TEXT DEFAULT ''")
        con.commit()
        con.close()

    def _init_csv(self):
        # Alte CSV (anderes Format) wegrotieren statt kaputt anzuhaengen
        if os.path.exists(self.csv_path):
            with open(self.csv_path, "r", encoding="utf-8") as f:
                first = f.readline().strip()
            if first != ",".join(CSV_HEADER):
                os.rename(self.csv_path, self.csv_path + ".alt")
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_HEADER)

    def save_event(self, result, frame=None, raw_frame=None, bbox=None,
                   punkte=None):
        length_m = 0.0
        ts = time.time()
        snap, snap_raw = "", ""
        if self.save_snapshots and frame is not None:
            fname = f"{int(ts*1000)}_{int(result['speed_kmh'])}kmh.jpg"
            try:
                cv2.imwrite(os.path.join(self.snapshot_dir, fname), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 85])
                snap = fname
            except Exception:
                snap = ""
        if self.save_snapshots and raw_frame is not None:
            fname_r = f"{int(ts*1000)}_{int(result['speed_kmh'])}kmh_raw.jpg"
            try:
                cv2.imwrite(os.path.join(self.snapshot_dir, fname_r),
                            raw_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                snap_raw = fname_r
            except Exception:
                snap_raw = ""
        bbox_json = json.dumps(bbox) if bbox else ""

        row = (ts, "Fahrzeug", result["speed_kmh"], result["direction"],
               result["distance_m"], result["duration_s"],
               result["samples"], snap, length_m, snap_raw, bbox_json,
               result.get("residual_m"))
        with self._lock:
            con = sqlite3.connect(self.db_path)
            row = tuple(row) + (result.get("erfassung", ""),
                                json.dumps(punkte) if punkte else "")
            cur = con.execute(
                "INSERT INTO events (ts,klasse,speed_kmh,richtung,distanz_m,"
                "dauer_s,samples,snapshot,laenge_m,snapshot_raw,bbox,"
                "residual_m,erfassung,punkte) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            event_id = cur.lastrowid
            con.commit()
            con.close()
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                    result["speed_kmh"], result["direction"], length_m,
                    result["distance_m"], result["duration_s"],
                    result["samples"], snap])
        return ts, event_id

    def update_class(self, event_id, klasse):
        with self._lock:
            con = sqlite3.connect(self.db_path)
            con.execute("UPDATE events SET klasse=? WHERE id=?",
                        (str(klasse), int(event_id)))
            con.commit()
            con.close()

    def delete(self, event_id):
        with self._lock:
            con = sqlite3.connect(self.db_path)
            row = con.execute(
                "SELECT snapshot, snapshot_raw FROM events WHERE id=?",
                (event_id,)).fetchone()
            con.execute("DELETE FROM events WHERE id=?", (event_id,))
            con.commit()
            con.close()
        if row:
            for fn in row:
                if fn:
                    try:
                        os.remove(os.path.join(self.snapshot_dir, fn))
                    except OSError:
                        pass
        return row is not None

    def delete_all(self):
        with self._lock:
            con = sqlite3.connect(self.db_path)
            rows = con.execute(
                "SELECT snapshot, snapshot_raw FROM events").fetchall()
            con.execute("DELETE FROM events")
            con.commit()
            con.close()
        for snap, snap_raw in rows:
            for fn in (snap, snap_raw):
                if fn:
                    try:
                        os.remove(os.path.join(self.snapshot_dir, fn))
                    except OSError:
                        pass

    @staticmethod
    def _build_where(min_kmh=None, max_kmh=None, richtung=None,
                     ts_from=None, ts_to=None, klasse=None):
        conds, params = [], []
        if klasse:
            conds.append("klasse = ?"); params.append(klasse)
        if min_kmh is not None:
            conds.append("speed_kmh >= ?"); params.append(min_kmh)
        if max_kmh is not None:
            conds.append("speed_kmh <= ?"); params.append(max_kmh)
        if richtung:
            conds.append("richtung = ?"); params.append(richtung)
        if ts_from is not None:
            conds.append("ts >= ?"); params.append(ts_from)
        if ts_to is not None:
            conds.append("ts < ?"); params.append(ts_to)
        return ((" WHERE " + " AND ".join(conds)) if conds else ""), params

    def query_events(self, limit=100, offset=0, **filters):
        where, params = self._build_where(**filters)
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        total = con.execute("SELECT COUNT(*) FROM events" + where,
                            params).fetchone()[0]
        light = con.execute(
            "SELECT ts, speed_kmh, richtung FROM events" + where,
            params).fetchall()
        rows = con.execute(
            "SELECT * FROM events" + where +
            " ORDER BY ts DESC LIMIT ? OFFSET ?",
            params + [limit, offset]).fetchall()
        con.close()
        return total, [dict(r) for r in rows], light

    def delete_where(self, **filters):
        where, params = self._build_where(**filters)
        with self._lock:
            con = sqlite3.connect(self.db_path)
            snaps = con.execute(
                "SELECT snapshot, snapshot_raw FROM events" + where,
                params).fetchall()
            con.execute("DELETE FROM events" + where, params)
            con.commit()
            con.close()
        for snap, snap_raw in snaps:
            for fn in (snap, snap_raw):
                if fn:
                    try:
                        os.remove(os.path.join(self.snapshot_dir, fn))
                    except OSError:
                        pass
        return len(snaps)

    def info(self):
        """Datenbank-/Datei-Groessen und Bestand fuer die System-Seite."""
        import shutil

        def fsize(p):
            try:
                return os.path.getsize(p)
            except OSError:
                return 0

        snap_bytes, snap_count = 0, 0
        try:
            for fn in os.listdir(self.snapshot_dir):
                fp = os.path.join(self.snapshot_dir, fn)
                if os.path.isfile(fp):
                    snap_bytes += fsize(fp)
                    snap_count += 1
        except OSError:
            pass
        con = sqlite3.connect(self.db_path)
        n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        rng = con.execute("SELECT MIN(ts), MAX(ts) FROM events").fetchone()
        con.close()
        try:
            du = shutil.disk_usage(os.path.dirname(self.db_path) or ".")
            disk = {"total": du.total, "used": du.used, "free": du.free}
        except OSError:
            disk = {"total": 0, "used": 0, "free": 0}
        return {"events": n,
                "oldest_ts": rng[0], "newest_ts": rng[1],
                "db_bytes": fsize(self.db_path),
                "csv_bytes": fsize(self.csv_path),
                "snapshot_bytes": snap_bytes,
                "snapshot_count": snap_count,
                "disk": disk}

    def speeds_since(self, since_ts):
        con = sqlite3.connect(self.db_path)
        rows = con.execute(
            "SELECT ts, speed_kmh, richtung FROM events WHERE ts > ? "
            "ORDER BY ts", (since_ts,)).fetchall()
        con.close()
        return rows

    def recent(self, limit=50):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]

    def stats(self):
        con = sqlite3.connect(self.db_path)
        cur = con.execute(
            "SELECT COUNT(*), AVG(speed_kmh), MAX(speed_kmh) FROM events")
        c, a, mx = cur.fetchone()
        # Verteilung der letzten 24h
        day = con.execute(
            "SELECT COUNT(*) FROM events WHERE ts > ?",
            (time.time() - 86400,)).fetchone()[0]
        lt = time.localtime()
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                                0, 0, 0, 0, 0, -1))
        today = con.execute(
            "SELECT COUNT(*) FROM events WHERE ts > ?",
            (midnight,)).fetchone()[0]
        con.close()
        return {"anzahl": c or 0, "schnitt_kmh": round(a or 0, 1),
                "max_kmh": round(mx or 0, 1), "letzte_24h": day,
                "heute": today}
