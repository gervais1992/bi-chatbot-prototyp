"""Abweichungsanalyse: erklaert, WORAUS sich eine Veraenderung zusammensetzt.

In der Business Intelligence genuegt es selten zu wissen, DASS eine Kennzahl
gestiegen ist -- entscheidend ist, woher der Unterschied kommt. Dieses Modul
zerlegt die Differenz zweier Jahre nach:

  * Dimensionsbeitraegen (Region, Kategorie, Kundensegment)
  * Mengen- und Preis-/Mixeffekt

Alle Werte stammen aus der Datenbank; es wird nichts geschaetzt.
"""
from __future__ import annotations

import duckdb

from .db import DB_PATH
from .state import AnalysisContext

# Dimensionen, nach denen der Beitrag aufgeschluesselt wird
DIMENSIONEN = [
    ("Region", "r.region",
     "JOIN dim_region r ON r.region_id = f.region_id"),
    ("Kategorie", "k.kategorie",
     "JOIN dim_produkt p ON p.produkt_id = f.produkt_id "
     "JOIN dim_kategorie k ON k.kategorie_id = p.kategorie_id"),
    ("Kundensegment", "ku.segment",
     "JOIN dim_kunde ku ON ku.kunde_id = f.kunde_id"),
]


def analyse(ctx: AnalysisContext, jahr_a: int, jahr_b: int,
            kennzahl: str = "umsatz") -> dict:
    """Zerlegt die Differenz der Kennzahl zwischen zwei Jahren."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # --- Gesamtdifferenz sowie Menge und Durchschnittspreis ---
        basis = con.execute(f"""
            SELECT z.jahr,
                   COUNT(*)            AS positionen,
                   SUM(f.menge)        AS menge,
                   SUM(f.{kennzahl})   AS wert
            FROM fakt_verkauf f
            JOIN dim_zeit z ON z.datum_id = f.datum_id
            WHERE z.jahr IN (?, ?)
            GROUP BY z.jahr ORDER BY z.jahr
        """, [min(jahr_a, jahr_b), max(jahr_a, jahr_b)]).fetchall()
        if len(basis) < 2:
            return {}

        (_, pos_a, menge_a, wert_a), (_, pos_b, menge_b, wert_b) = basis
        menge_a, menge_b = float(menge_a), float(menge_b)
        wert_a, wert_b = float(wert_a), float(wert_b)
        delta = wert_b - wert_a

        preis_a = wert_a / menge_a if menge_a else 0.0
        preis_b = wert_b / menge_b if menge_b else 0.0

        ergebnis = {
            "jahr_a": min(jahr_a, jahr_b), "jahr_b": max(jahr_a, jahr_b),
            "kennzahl": kennzahl,
            "wert_a": wert_a, "wert_b": wert_b, "delta": delta,
            "prozent": (wert_b / wert_a - 1) * 100 if wert_a else 0.0,
            "positionen_a": int(pos_a), "positionen_b": int(pos_b),
            "menge_a": menge_a, "menge_b": menge_b,
            "preis_a": preis_a, "preis_b": preis_b,
            # Klassische Zerlegung: Mengeneffekt zu altem Preis,
            # Preis-/Mixeffekt auf neuer Menge.
            "mengeneffekt": (menge_b - menge_a) * preis_a,
            "preiseffekt": menge_b * (preis_b - preis_a),
            "beitraege": {},
        }

        # --- Beitrag je Dimension ---
        for name, spalte, joins in DIMENSIONEN:
            zeilen = con.execute(f"""
                SELECT {spalte} AS auspraegung,
                       SUM(CASE WHEN z.jahr = ? THEN f.{kennzahl} ELSE 0 END) AS a,
                       SUM(CASE WHEN z.jahr = ? THEN f.{kennzahl} ELSE 0 END) AS b
                FROM fakt_verkauf f
                JOIN dim_zeit z ON z.datum_id = f.datum_id
                {joins}
                WHERE z.jahr IN (?, ?)
                GROUP BY 1 ORDER BY 1
            """, [ergebnis["jahr_a"], ergebnis["jahr_b"],
                  ergebnis["jahr_a"], ergebnis["jahr_b"]]).fetchall()
            ergebnis["beitraege"][name] = [
                {"name": z[0], "a": float(z[1]), "b": float(z[2]),
                 "delta": float(z[2]) - float(z[1]),
                 "anteil": (float(z[2]) - float(z[1])) / delta * 100 if delta else 0.0}
                for z in zeilen
            ]
        return ergebnis
    finally:
        con.close()


def describe(erg: dict) -> str:
    """Formuliert das Analyseergebnis als lesbaren deutschen Text."""
    if not erg:
        return "Für den Vergleich liegen nicht genügend Daten vor."

    from .narrative import _zahl

    def pz(p: float) -> str:
        return f"{p:+.1f}".replace(".", ",") + " %"

    def anzahl(n: int) -> str:
        return f"{n:,}".replace(",", ".")      # nur Tausendertrennzeichen

    label = erg["kennzahl"].capitalize()
    zeilen = [
        f"**Abweichungsanalyse {label}: {erg['jahr_a']} → {erg['jahr_b']}**",
        f"{_zahl(erg['wert_a'])} → {_zahl(erg['wert_b'])} "
        f"= **{_zahl(erg['delta'])}** ({pz(erg['prozent'])})",
    ]

    m, p = erg["mengeneffekt"], erg["preiseffekt"]
    zeilen.append(
        f"*Zerlegung:* Mengeneffekt {_zahl(m)} "
        f"({anzahl(erg['positionen_a'])} → {anzahl(erg['positionen_b'])} "
        f"Positionen), Preis-/Mixeffekt {_zahl(p)} "
        f"(Ø {_zahl(erg['preis_a'])} → {_zahl(erg['preis_b'])} je Einheit)."
    )

    # Groesste Treiber je Dimension
    for name, posten in erg["beitraege"].items():
        sortiert = sorted(posten, key=lambda x: abs(x["delta"]), reverse=True)
        teile = [f"{x['name']}: {_zahl(x['delta'])} ({x['anteil']:.0f} %)"
                 for x in sortiert[:4]]
        zeilen.append(f"*Nach {name}:* " + " · ".join(teile))

    return "\n\n".join(zeilen)
