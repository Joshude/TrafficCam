"""Geometrie: Bodenebenen-Homographie + robuste Geschwindigkeitsschätzung.

Kernidee gegen das "vorne/hinten"-Problem:
Statt einer festen Meter-pro-Pixel-Konstante wird die schraege Kameraperspektive
per Homographie auf eine metrische Draufsicht der Strassenebene abgebildet.
Ein nahes und ein fernes Fahrzeug werden dadurch beide korrekt in Metern
gemessen -- unabhaengig davon, ob sie auf der nahen oder fernen Spur fahren.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


class Distortion:
    """Ein-Parameter-Fisheye-Modell (Division Model).

    undistort:  u = c + (p - c) / (1 + lam * r^2),  r = |p - c| / scale
    Ein einziger Parameter lam genuegt, um typische Fisheye-Kruemmung fuer
    Messzwecke zu korrigieren; geschaetzt wird er daraus, dass real gerade
    Kanten (Bordstein, Zaun) nach der Entzerrung gerade sein muessen.
    """

    def __init__(self, lam, cx, cy, scale):
        self.lam = float(lam)
        self.cx = float(cx)
        self.cy = float(cy)
        self.scale = float(scale)

    def undistort(self, pts):
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        nx = (p[:, 0] - self.cx) / self.scale
        ny = (p[:, 1] - self.cy) / self.scale
        denom = 1.0 + self.lam * (nx * nx + ny * ny)
        # Nahe der Modell-Singularitaet (starkes Fisheye, Bildecken):
        # Punkte verwerfen statt ins Absurde zu projizieren.
        valid = denom > 0.05
        f = 1.0 / np.where(valid, denom, 1.0)
        out = np.stack([self.cx + self.scale * nx * f,
                        self.cy + self.scale * ny * f], axis=1)
        out[~valid] = np.nan
        return out

    def redistort(self, pts):
        """Inverse: entzerrte -> verzerrte Pixel (fuers Gitter-Zeichnen)."""
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        ux = (p[:, 0] - self.cx) / self.scale
        uy = (p[:, 1] - self.cy) / self.scale
        ru = np.hypot(ux, uy)
        if abs(self.lam) < 1e-12:
            return p.copy()
        disc = 1.0 - 4.0 * self.lam * ru * ru
        valid = disc >= 0.0
        disc = np.clip(disc, 0.0, None)
        denom = 2.0 * self.lam * np.where(ru < 1e-9, 1.0, ru)
        rd = np.where(ru < 1e-9, ru, (1.0 - np.sqrt(disc)) / denom)
        safe_ru = np.where(ru < 1e-9, 1.0, ru)
        s = np.where(ru < 1e-9, 1.0, rd / safe_ru)
        out = np.stack([self.cx + self.scale * ux * s,
                        self.cy + self.scale * uy * s], axis=1)
        # Ungueltig ausserhalb des Modellbereichs: lam>0 -> disc<0;
        # lam<0 -> Saettigung (rd konvergiert, ferne Punkte stapeln sich).
        # Robustes Kriterium fuer beide Faelle: lokale Kompression s=rd/ru
        # weicht stark von 1 ab -> nicht mehr zeichnen.
        valid = valid & (s > 0.4) & (s < 2.5)
        out[~valid] = np.nan
        return out


def estimate_lambda(lines, cx, cy, scale):
    """Schaetzt lam so, dass die geklickten Linien nach Entzerrung
    maximal gerade sind. lines: Liste von Punktlisten [[x,y],...].
    Rueckgabe: (lam, kosten_ohne, kosten_mit)."""
    def cost(lam):
        d = Distortion(lam, cx, cy, scale)
        total = 0.0
        for ln in lines:
            u = d.undistort(np.asarray(ln, dtype=np.float64))
            u = u - u.mean(axis=0)
            ev = np.linalg.eigvalsh(u.T @ u)
            total += float(ev[0])   # Quer-Streuung = Kruemmungsmass
        return total

    coarse = np.linspace(-1.5, 1.5, 601)
    lam = min(coarse, key=cost)
    lo, hi = lam - 0.01, lam + 0.01
    for _ in range(60):                     # Ternaersuche verfeinern
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        if cost(m1) < cost(m2):
            hi = m2
        else:
            lo = m1
    lam = (lo + hi) / 2
    return float(lam), cost(0.0), cost(lam)


class GroundPlane:
    """Homographie Bild -> Welt, optional mit Fisheye-Entzerrung davor."""

    def __init__(self, image_points, world_points, dist=None):
        self.dist = dist
        src = np.array(image_points, dtype=np.float32)
        if dist is not None:
            src = dist.undistort(src).astype(np.float32)
        dst = np.array(world_points, dtype=np.float32)
        if len(src) < 4 or len(src) != len(dst):
            raise ValueError("Mindestens 4 zueinander passende Punkte noetig")
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if H is None:
            raise ValueError("Homographie konnte nicht berechnet werden")
        self.H = H

    def to_world(self, points):
        """Bildpunkte (verzerrte Pixel) -> Weltkoordinaten (Meter).

        Punkte jenseits des Entzerrungs-Modellbereichs kommen als NaN
        zurueck (cv2.perspectiveTransform wuerde NaN sonst zu 0,0 machen).
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
        bad = None
        if self.dist is not None:
            pts = self.dist.undistort(pts)
            bad = ~np.all(np.isfinite(pts), axis=1)
            pts = np.nan_to_num(pts).astype(np.float32)
        w = cv2.perspectiveTransform(pts.reshape(-1, 1, 2),
                                     self.H).reshape(-1, 2)
        if bad is not None and bad.any():
            w = w.astype(np.float64)
            w[bad] = np.nan
        return w


def ground_point(bbox):
    """Bodenkontaktpunkt eines Fahrzeugs = Unterkante-Mitte der Box."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def point_in_polygon(point, polygon):
    if not polygon:
        return True
    poly = np.array(polygon, dtype=np.int32)
    return cv2.pointPolygonTest(poly, (float(point[0]), float(point[1])), False) >= 0


def side_of_line(point, line):
    """Vorzeichen sagt, auf welcher Seite der Linie der Punkt liegt.

    line = [[x1,y1],[x2,y2]]. Wechselt das Vorzeichen zwischen zwei Frames,
    hat der Punkt die Linie ueberquert.
    """
    (x1, y1), (x2, y2) = line
    px, py = point
    return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)


def estimate_speed(samples, min_samples, min_time, min_disp, max_kmh):
    """Schaetzt Geschwindigkeit aus Track-Samples.

    samples: Liste von (t, world_x, world_y, img_x, img_y)
    Rueckgabe: dict oder None bei zu wenig/unplausiblen Daten.
    """
    if len(samples) < min_samples:
        return None

    t = np.array([s[0] for s in samples], dtype=np.float64)
    wx = np.array([s[1] for s in samples], dtype=np.float64)
    wy = np.array([s[2] for s in samples], dtype=np.float64)
    t = t - t[0]

    dt = float(t[-1] - t[0])
    if dt < min_time:
        return None

    disp = math.hypot(wx[-1] - wx[0], wy[-1] - wy[0])
    if disp < min_disp:
        return None

    # Geschwindigkeit entlang der Hauptbewegungsachse (PCA):
    # Quer-Rauschen des Bodenpunkts (Schatten, Blob-Kanten) faellt damit
    # per Konstruktion aus der Messung heraus, statt sie via hypot(vx,vy)
    # systematisch nach oben zu verfaelschen.
    pts = np.stack([wx, wy], axis=1)
    center = pts.mean(axis=0)
    d = pts - center
    cov = d.T @ d
    evals, evecs = np.linalg.eigh(cov)
    axis = evecs[:, -1]                    # Richtung groesster Bewegung
    s = d @ axis                           # 1D-Position entlang der Achse

    def _robust_slope(tv, sv):
        """Linearer Fit mit einer Runde Ausreisser-Verwerfung (2.5 sigma)."""
        k, b = np.polyfit(tv, sv, 1)
        resid = sv - (k * tv + b)
        sigma = float(np.std(resid))
        if sigma > 1e-9:
            keep = np.abs(resid) <= 2.5 * sigma
            if keep.sum() >= max(4, len(tv) // 2) and keep.sum() < len(tv):
                k, b = np.polyfit(tv[keep], sv[keep], 1)
                resid = sv[keep] - (k * tv[keep] + b)
        return float(k), float(np.sqrt(np.mean(resid ** 2)))

    slope, residual = _robust_slope(t, s)
    speed_kmh = abs(slope) * 3.6

    if not (0 < speed_kmh <= max_kmh):
        return None

    # Strecke aus dem Fit (endpunkt-rauschunempfindlich)
    fit_dist = abs(slope) * dt

    img_x0 = samples[0][3]
    img_x1 = samples[-1][3]
    direction = "links->rechts" if img_x1 > img_x0 else "rechts->links"

    return {
        "speed_kmh": round(speed_kmh, 1),
        "direction": direction,
        "distance_m": round(fit_dist, 2),
        "duration_s": round(dt, 3),
        "samples": len(samples),
        "residual_m": round(residual, 3),
    }
