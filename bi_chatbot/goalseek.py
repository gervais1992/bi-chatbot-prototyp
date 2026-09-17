"""Zielwertsuche: "Was haette geschehen muessen, um Ziel X zu erreichen?"

Waehrend die Abweichungsanalyse (variance.py) erklaert, WORAUS eine
Veraenderung bestand, beantwortet dieses Modul die umgekehrte Frage: welche
Groessen haetten sich wie veraendern muessen, damit ein Zielwert erreicht
worden waere.

Das Ergebnis ist eine rechnerische Umkehrung der Ist-Zahlen -- keine Aussage
darueber, ob ein Weg betriebswirtschaftlich realistisch ist. Genau das wird
dem Nutzer auch mitgeteilt.
"""
from __future__ import annotations

import duckdb

from .db import DB_PATH
from .state import AnalysisContext

WERKTAGE_PRO_JAHR = 261      # Naeherung fuer die Umrechnung je Werktag


def _kennzahlen(jahr: int, kennzahl: str) -> dict | None:
    """Ist-Werte eines Jahres: Wert, Positionen, Menge, Kunden."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        zeile = con.execute(f"""
            SELECT SUM(f.{kennzahl})          AS wert,
                   COUNT(*)                   AS positionen,
                   SUM(f.menge)               AS menge,
                   COUNT(DISTINCT f.kunde_id) AS kunden
            FROM fakt_verkauf f
            JOIN dim_zeit z ON z.datum_id = f.datum_id
            WHERE z.jahr = ?
        """, [jahr]).fetchone()
    finally:
        con.close()
    if not zeile or zeile[0] is None:
        return None
    return {"wert": float(zeile[0]), "positionen": int(zeile[1]),
            "menge": float(zeile[2]), "kunden": int(zeile[3])}


def analyse(ctx: AnalysisContext, basis_jahr: int,
            ziel_wert: float | None = None, ziel_jahr: int | None = None,
            kennzahl: str = "umsatz") -> dict:
    """Berechnet, was im Basisjahr noetig gewesen waere.

    Entweder `ziel_wert` direkt angeben oder `ziel_jahr`, dessen Ist-Wert
    dann als Ziel dient.
    """
    ist = _kennzahlen(basis_jahr, kennzahl)
    if ist is None:
        return {}

    if ziel_wert is None:
        if ziel_jahr is None:
            return {}
        ziel = _kennzahlen(ziel_jahr, kennzahl)
        if ziel is None:
            return {}
        ziel_wert = ziel["wert"]

    luecke = ziel_wert - ist["wert"]
    faktor = ziel_wert / ist["wert"] if ist["wert"] else 0.0
    preis = ist["wert"] / ist["menge"] if ist["menge"] else 0.0

    return {
        "basis_jahr": basis_jahr, "ziel_jahr": ziel_jahr,
        "kennzahl": kennzahl,
        "ist": ist["wert"], "ziel": ziel_wert,
        "luecke": luecke, "faktor": faktor,
        "erreicht": luecke <= 0,
        # Drei Hebel, jeweils fuer sich allein betrachtet
        "menge_ist": ist["menge"], "menge_soll": ist["menge"] * faktor,
        "positionen_ist": ist["positionen"],
        "positionen_soll": ist["positionen"] * faktor,
        "je_werktag": (ist["positionen"] * faktor - ist["positionen"])
                      / WERKTAGE_PRO_JAHR,
        "preis_ist": preis, "preis_soll": preis * faktor,
        "kunden_ist": ist["kunden"], "kunden_soll": ist["kunden"] * faktor,
        "umsatz_je_kunde": ist["wert"] / ist["kunden"] if ist["kunden"] else 0.0,
    }


def describe(erg: dict) -> str:
    """Formuliert die Zielwertsuche als lesbaren deutschen Text."""
    if not erg:
        return "Für die Zielwertsuche liegen nicht genügend Daten vor."

    from .narrative import _zahl

    def pz(p: float) -> str:
        return f"{p:+.1f}".replace(".", ",") + " %"

    def komma(x: float) -> str:
        return f"{x:.1f}".replace(".", ",")

    def anz(n: float) -> str:
        return f"{int(round(n)):,}".replace(",", ".")

    label = erg["kennzahl"].capitalize()
    ziel_txt = (f"{label} {erg['ziel_jahr']}" if erg["ziel_jahr"]
                else f"Zielwert {_zahl(erg['ziel'])}")

    if erg["erreicht"]:
        return (f"**Zielwertsuche {erg['basis_jahr']}** — der {label} lag "
                f"bereits bei {_zahl(erg['ist'])} und damit über dem Ziel "
                f"{_zahl(erg['ziel'])}. Es wäre nichts nötig gewesen.")

    zeilen = [
        f"**Zielwertsuche: {ziel_txt} bereits {erg['basis_jahr']} erreichen**",
        f"Ist {erg['basis_jahr']}: {_zahl(erg['ist'])} · Ziel: "
        f"{_zahl(erg['ziel'])} · Lücke: **{_zahl(erg['luecke'])}** "
        f"({pz((erg['faktor'] - 1) * 100)})",
        "*Jeder Hebel für sich allein betrachtet:*",
        f"· **Menge:** {anz(erg['menge_ist'])} → {anz(erg['menge_soll'])} "
        f"Einheiten, d. h. {anz(erg['positionen_ist'])} → "
        f"{anz(erg['positionen_soll'])} Positionen "
        f"(rund {komma(erg['je_werktag'])} zusätzliche je Werktag)",
        f"· **Preis:** Ø {_zahl(erg['preis_ist'])} → {_zahl(erg['preis_soll'])} "
        f"je Einheit",
        f"· **Kunden:** {anz(erg['kunden_ist'])} → {anz(erg['kunden_soll'])} "
        f"(rund {anz(erg['kunden_soll'] - erg['kunden_ist'])} zusätzliche "
        f"mit je Ø {_zahl(erg['umsatz_je_kunde'])})",
        "_Rechnerische Umkehrung der Ist-Zahlen. In der Praxis wäre eine "
        "Kombination der Hebel realistischer; ob ein Weg erreichbar gewesen "
        "wäre, sagt die Rechnung nicht._",
    ]
    return "\n\n".join(zeilen)
