"""Verfeinert unsichere Kalibrierpunkte anhand bekannter Fahrzeuglaengen.

Idee: Manche Kalibrierpunkte sind hart vermessen (Zaunpfosten-Abstand per
Maßband) und bleiben fix. Andere wurden nur nach Augenmaß/Gitteroptik
platziert (typischerweise die ferne Fahrbahnseite) und sind der Grund fuer
systematische Geschwindigkeitsfehler dort. Referenzmessungen (zwei Bildpunkte
+ deren bekannte reale Laenge, z.B. ein Radstand) liefern Grundwahrheit, mit
der die unsicheren Punkte per kleiner Optimierung neu platziert werden -
die Homographie wird dabei mit den bestehenden Werkzeugen (GroundPlane) neu
gerechnet, nur die (X,Y)-Weltkoordinaten der "unsicheren" Punkte sind frei.
"""
from __future__ import annotations

import numpy as np

from .geometry import GroundPlane


def _predict_length(image_points, world_points, dist, p1, p2):
    try:
        plane = GroundPlane(image_points, world_points, dist=dist)
    except Exception:
        return None
    w = plane.to_world([p1, p2])
    if not np.all(np.isfinite(w)):
        return None
    return float(np.hypot(w[0, 0] - w[1, 0], w[0, 1] - w[1, 1]))


def report_for(image_points, world_points, dist, references):
    """Vergleicht aktuelle Kalibrierung mit den Referenzmessungen."""
    out = []
    for ref in references:
        d = _predict_length(image_points, world_points, dist,
                            ref["p1"], ref["p2"])
        err = (round(100.0 * (d - ref["length"]) / ref["length"], 1)
               if d is not None else None)
        out.append({"length": ref["length"],
                    "predicted": round(d, 3) if d is not None else None,
                    "error_pct": err})
    return out


def refine_points(image_points, world_points, fixed_mask, references,
                  dist=None, reg=0.0004, rounds=8, search_span=8.0):
    """Optimiert die Weltkoordinaten der nicht-fixen Punkte.

    fixed_mask: Liste bool, True = Punkt bleibt unveraendert (vermessen).
    references: Liste {"p1":[x,y], "p2":[x,y], "length": meter}.
    Rueckgabe: (neue_world_points, report, warnung_oder_None)
    """
    free_idx = [i for i, f in enumerate(fixed_mask) if not f]
    if not free_idx:
        return (world_points,
                report_for(image_points, world_points, dist, references),
                "Keine unsicheren Punkte ausgewaehlt - nichts zu tun")
    if not references:
        return (world_points,
                report_for(image_points, world_points, dist, references),
                "Keine Referenzmessungen vorhanden")

    n_unknown = 2 * len(free_idx)
    warn = None
    if len(references) < max(1, n_unknown // 2):
        warn = (f"Wenig Referenzmessungen ({len(references)}) fuer "
                f"{len(free_idx)} unsichere Punkte - Ergebnis mit Vorsicht "
                "geniessen, mehr Referenzen an unterschiedlichen Stellen "
                "verbessern die Genauigkeit")

    init = np.array(world_points, dtype=float)
    params0 = np.concatenate([init[i] for i in free_idx])

    def build_world(params):
        wp = init.copy()
        for k, i in enumerate(free_idx):
            wp[i] = params[2 * k:2 * k + 2]
        return wp.tolist()

    def cost(params):
        wp = build_world(params)
        total = 0.0
        for ref in references:
            d = _predict_length(image_points, wp, dist, ref["p1"], ref["p2"])
            if d is None:
                total += 4.0
                continue
            err = (d - ref["length"]) / max(ref["length"], 0.1)
            total += err * err
        total += reg * float(np.sum((params - params0) ** 2))
        return total

    params = params0.copy()
    span = float(search_span)
    for _ in range(rounds):
        for i in range(len(params)):
            lo, hi = params[i] - span, params[i] + span
            for _ in range(40):
                m1 = lo + (hi - lo) / 3
                m2 = hi - (hi - lo) / 3
                p1, p2 = params.copy(), params.copy()
                p1[i], p2[i] = m1, m2
                if cost(p1) < cost(p2):
                    hi = m2
                else:
                    lo = m1
            params[i] = (lo + hi) / 2
        span *= 0.5

    wp_final = build_world(params)
    return (wp_final, report_for(image_points, wp_final, dist, references),
            warn)
