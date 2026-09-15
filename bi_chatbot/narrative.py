"""Textuelle Zusammenfassung des Diagramminhalts.

Der Text wird deterministisch aus den tatsaechlich geladenen Werten erzeugt --
nicht vom Sprachmodell formuliert. So kann der Chatbot konkrete Zahlen nennen,
ohne dass die Gefahr erfundener Werte besteht (kleine Modelle neigen genau
dazu). Die Zahlen im Text und im Diagramm stammen damit immer aus derselben
Abfrage.
"""
from __future__ import annotations

from . import semantic_layer as sem
from .state import AnalysisContext


def _deutsch(zahl: str) -> str:
    """Englische Trennzeichen in deutsche umwandeln (nur der Zahlteil)."""
    return zahl.replace(",", "#").replace(".", ",").replace("#", ".")


def _zahl(wert: float) -> str:
    """Formatiert einen Eurobetrag kompakt in deutscher Schreibweise."""
    if abs(wert) >= 1_000_000:
        return f"{_deutsch(f'{wert / 1_000_000:,.2f}')} Mio. €"
    if abs(wert) >= 1_000:
        return f"{_deutsch(f'{wert / 1_000:,.1f}')} Tsd. €"
    return f"{_deutsch(f'{wert:,.2f}')} €"


def _prozent(neu: float, alt: float) -> str | None:
    if not alt:
        return None
    p = (neu / alt - 1) * 100
    return f"{p:+.1f}".replace(".", ",") + " %"


def describe(ctx: AnalysisContext, labels: list[str],
             base: dict[str, list[float]], max_punkte: int = 6,
             prognose: set[str] | None = None) -> str:
    """Erzeugt eine kurze Beschreibung der aktuell dargestellten Daten."""
    if not ctx.series or not labels:
        return ""

    haupt = ctx.series[0]
    werte = sem.compute_series_values(haupt.key, base, ctx)
    if not werte:
        return ""

    achse = sem.GROUPINGS.get(ctx.group_by)
    achsen_name = achse.label if achse else ctx.group_by
    prognose = prognose or set()
    teile: list[str] = []

    # Veraenderungsraten sind nur bei geordneten (Zeit-)Achsen sinnvoll.
    # Zwischen Kategorien oder Produkten waere "+12 %" irrefuehrend.
    zeitachse = ctx.group_by not in sem.SACHDIMENSIONEN

    if len(labels) <= max_punkte:
        # Wenige Punkte: alle einzeln nennen
        posten = []
        for i, (lab, wert) in enumerate(zip(labels, werte)):
            eintrag = f"{lab}: {_zahl(wert)}"
            if lab in prognose:
                eintrag += " *(Prognose)*"
            if zeitachse and i > 0:
                p = _prozent(wert, werte[i - 1])
                if p:
                    eintrag += f" ({p})"
            posten.append(eintrag)
        teile.append(f"**{haupt.label}** nach {achsen_name} — "
                     + " · ".join(posten))
    else:
        # Viele Punkte: Kennwerte statt Aufzaehlung
        hoch = max(range(len(werte)), key=lambda i: werte[i])
        tief = min(range(len(werte)), key=lambda i: werte[i])
        gesamt = sum(werte)
        satz = (f"**{haupt.label}** nach {achsen_name} — Summe "
                f"{_zahl(gesamt)}, Durchschnitt {_zahl(gesamt / len(werte))}. "
                f"Höchster Wert: {labels[hoch]} mit {_zahl(werte[hoch])}, "
                f"niedrigster: {labels[tief]} mit {_zahl(werte[tief])}.")
        if zeitachse:
            p = _prozent(werte[-1], werte[0])
            if p:
                satz += f" Von {labels[0]} bis {labels[-1]}: {p}."
        teile.append(satz)

    # Weitere Reihen nur mit ihrer Summe erwaehnen
    for reihe in ctx.series[1:]:
        w = sem.compute_series_values(reihe.key, base, ctx)
        if w:
            teile.append(f"{reihe.label} gesamt: {_zahl(sum(w))}.")

    return "\n\n".join(teile)
