"""Einfache Trendprognose fuer Jahre ohne Datenbestand.

Verfahren: lineare Regression (Methode der kleinsten Quadrate) ueber die
Jahressummen der jeweiligen Kennzahl. Bewusst schlicht gehalten und
nachvollziehbar -- kein Blackbox-Modell.

WICHTIG: Prognosewerte sind KEINE Messwerte. Sie werden im Diagramm gestrichelt
dargestellt und im Text ausdruecklich als Prognose gekennzeichnet. Bei nur
wenigen Stuetzjahren und grossem Abstand zum Datenbestand ist die Aussagekraft
gering; `guete_hinweis()` formuliert diese Einschraenkung fuer den Nutzer.
"""
from __future__ import annotations


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Kleinste-Quadrate-Gerade y = a * x + b. Gibt (a, b) zurueck."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    nenner = sum((x - mx) ** 2 for x in xs)
    if nenner == 0:
        return 0.0, my
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / nenner
    return a, my - a * mx


def bestimmtheitsmass(xs: list[float], ys: list[float]) -> float:
    """R^2 der Regressionsgeraden -- Mass fuer die Trendtreue der Daten."""
    if len(ys) < 2:
        return 0.0
    a, b = linear_fit(xs, ys)
    my = sum(ys) / len(ys)
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a * x + b)) ** 2 for x, y in zip(xs, ys))
    return 1.0 - ss_res / ss_tot if ss_tot else 0.0


def predict(labels: list[str], base: dict[str, list[float]],
            ziel_jahre: list[int]) -> tuple[list[str], dict[str, list[float]], set[str]]:
    """Ergaenzt die Reihen um Prognosewerte fuer die genannten Jahre.

    Erwartet eine nach Jahren gruppierte Auswertung. Rueckgabe:
    (labels, werte, menge_der_prognosejahre) -- chronologisch sortiert.
    """
    if not labels or not ziel_jahre:
        return labels, base, set()

    try:
        jahre = [int(l) for l in labels]
    except ValueError:            # keine Jahresachse -> keine Prognose
        return labels, base, set()

    neue = sorted(set(ziel_jahre) - set(jahre))
    if not neue:
        return labels, base, set()

    alle = sorted(jahre + neue)
    xs = [float(j) for j in jahre]

    erweitert: dict[str, list[float]] = {}
    for kennzahl, werte in base.items():
        a, b = linear_fit(xs, [float(w) for w in werte])
        bekannt = dict(zip(jahre, werte))
        erweitert[kennzahl] = [
            float(bekannt.get(j, max(0.0, a * j + b))) for j in alle
        ]

    return [str(j) for j in alle], erweitert, {str(j) for j in neue}


def guete_hinweis(labels: list[str], werte: list[float],
                  ziel_jahre: list[int]) -> str:
    """Formuliert die Verlaesslichkeit der Prognose in einem Satz."""
    try:
        jahre = [int(l) for l in labels]
    except ValueError:
        return ""
    if len(jahre) < 2 or not ziel_jahre:
        return ""

    r2 = bestimmtheitsmass([float(j) for j in jahre], [float(w) for w in werte])
    abstand = max(
        max(0, min(jahre) - min(ziel_jahre)),
        max(0, max(ziel_jahre) - max(jahre)),
    )
    hinweis = (f"Lineare Trendfortschreibung auf Basis von {len(jahre)} "
               f"Jahren (Bestimmtheitsmaß R² = {r2:.2f}".replace(".", ",") + ").")
    if abstand > 3:
        hinweis += (f" Der Abstand zum Datenbestand beträgt {abstand} Jahre – "
                    "die Werte sind daher nur grob orientierend.")

    # Rueckwaertsfortschreibung laeuft bei steigendem Trend schnell ins
    # Negative. Das ist fachlich unsinnig und muss benannt werden.
    a, b = linear_fit([float(j) for j in jahre], [float(w) for w in werte])
    if any(a * j + b <= 0 for j in ziel_jahre):
        hinweis += (" Für mindestens ein Zieljahr ergibt die Trendgerade einen "
                    "Wert von null oder weniger: eine Rückrechnung so weit vor "
                    "den Datenbestand ist fachlich nicht belastbar.")
    return hinweis
