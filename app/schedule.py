"""Zeit-/Sonnenstands-Steuerung des Trackings.

Sonnenauf-/untergang nach der Standard-"Sunrise equation" (NOAA/Wikipedia),
komplett offline berechnet.
"""
from __future__ import annotations

import math
import time


def sun_epochs(lat, lon, t=None):
    """Sonnenaufgang/-untergang (Unix-Epoch) fuer den Tag um Zeitpunkt t."""
    if t is None:
        t = time.time()
    jd = t / 86400.0 + 2440587.5
    n = round(jd - 2451545.0 + 0.0008 + lon / 360.0)
    jstar = n - lon / 360.0
    M = math.radians((357.5291 + 0.98560028 * jstar) % 360.0)
    C = (1.9148 * math.sin(M) + 0.02 * math.sin(2 * M)
         + 0.0003 * math.sin(3 * M))
    lam = math.radians((math.degrees(M) + C + 180.0 + 102.9372) % 360.0)
    jtransit = (2451545.0 + jstar + 0.0053 * math.sin(M)
                - 0.0069 * math.sin(2 * lam))
    sindelta = math.sin(lam) * math.sin(math.radians(23.4397))
    delta = math.asin(sindelta)
    phi = math.radians(lat)
    cosw = ((math.sin(math.radians(-0.833))
             - math.sin(phi) * sindelta)
            / (math.cos(phi) * math.cos(delta)))
    cosw = max(-1.0, min(1.0, cosw))
    w = math.degrees(math.acos(cosw)) / 360.0
    to_epoch = lambda J: (J - 2440587.5) * 86400.0
    return to_epoch(jtransit - w), to_epoch(jtransit + w)


def _parse_hm(s):
    try:
        h, m = str(s).strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def tracking_active(cfg, t=None):
    """(aktiv, grund) anhand der Settings. cfg = settings.get()."""
    if t is None:
        t = time.time()
    mode = cfg.get("tracking_mode", "immer")
    if mode == "zeit":
        von = _parse_hm(cfg.get("aktiv_von"))
        bis = _parse_hm(cfg.get("aktiv_bis"))
        if von is None or bis is None:
            return True, "Zeitfenster ungueltig - aktiv"
        lt = time.localtime(t)
        now = lt.tm_hour * 60 + lt.tm_min
        if von <= bis:
            active = von <= now < bis
        else:                       # Fenster ueber Mitternacht
            active = now >= von or now < bis
        return active, ("aktiv (Zeitfenster)" if active
                        else "pausiert (Zeitfenster)")
    if mode == "sonne":
        try:
            rise, sset = sun_epochs(float(cfg.get("lat", 0)),
                                    float(cfg.get("lon", 0)), t)
        except Exception:
            return True, "Sonnenberechnung fehlgeschlagen - aktiv"
        off = float(cfg.get("sonnen_offset_min", 0)) * 60.0
        active = (rise - off) <= t <= (sset + off)
        return active, ("aktiv (Tageslicht)" if active
                        else "pausiert (Nacht)")
    return True, "aktiv"
