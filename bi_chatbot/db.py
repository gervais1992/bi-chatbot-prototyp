"""Datenzugriff (BI-/Query-Modul).

Kapselt DuckDB. Laedt Basiskennzahlen (Umsatz, Kosten) fuer den aktuellen
Filter und das gewaehlte Aggregationsniveau der Zeitachse.

Wichtig fuer die Sicherheit: die SQL-Fragmente fuer die Gruppierung stammen
ausschliesslich aus dem kontrollierten Vokabular `sem.GROUPINGS`, niemals aus
der Nutzereingabe. Werte werden als Parameter uebergeben.

Abgeleitete Kennzahlen (KPIs) werden NICHT hier, sondern in der semantischen
Schicht berechnet.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import semantic_layer as sem
from .state import AnalysisContext

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bi_demo.duckdb"

MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
          "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _ensure_db() -> None:
    if not DB_PATH.exists():
        # Datenbank bei Bedarf automatisch erzeugen
        import create_data
        create_data.build()


def _connect():
    _ensure_db()
    return duckdb.connect(str(DB_PATH), read_only=True)


def available_regions(jahr: int = 2025) -> list[str]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT DISTINCT region FROM sales WHERE jahr = ? ORDER BY region",
            [jahr],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def available_years() -> list[int]:
    """Alle Jahre, fuer die tatsaechlich Daten vorliegen."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT DISTINCT jahr FROM dim_zeit ORDER BY jahr").fetchall()
    finally:
        con.close()
    return [int(r[0]) for r in rows]


def load_base_measures(
    ctx: AnalysisContext,
) -> tuple[list[str], dict[str, list[float]]]:
    """Laedt die Basiskennzahlen fuer den aktuellen Kontext.

    Rueckgabe: (achsenbeschriftungen, {kennzahl: werte}) -- beide gleich lang
    und nach der Zeitachse sortiert.
    """
    measures = ctx.base_measures()
    grouping = sem.GROUPINGS.get(ctx.group_by) or sem.GROUPINGS["monat"]

    # Aggregatspalten stammen nur aus dem Vokabular, nie aus Nutzereingabe.
    agg = ", ".join(f"SUM(f.{sem.MEASURES[m].column}) AS {m}" for m in measures)

    where: list[str] = []
    params: list = []
    # Beim Jahresvergleich darf der Jahresfilter nicht greifen.
    if ctx.group_by != "jahr":
        where.append("z.jahr = ?")
        params.append(ctx.jahr)
    if ctx.region:
        where.append("r.region = ?")
        params.append(ctx.region)
    if ctx.quartal:
        where.append("z.quartal = ?")
        params.append(ctx.quartal)
    if ctx.kategorie:
        where.append("k.kategorie = ?")
        params.append(ctx.kategorie)
    if ctx.nur_werktage:
        where.append("z.ist_wochenende = false")

    # Zusaetzliche Verbunde nur dann, wenn Achse oder Filter sie brauchen.
    # Die Fragmente stammen aus dieser festen Tabelle, nie aus Nutzereingabe.
    JOINS = {
        "produkt": "JOIN dim_produkt   p  ON p.produkt_id  = f.produkt_id",
        "kategorie": "JOIN dim_kategorie k ON k.kategorie_id = p.kategorie_id",
        "kunde": "JOIN dim_kunde     ku ON ku.kunde_id    = f.kunde_id",
    }
    noetig: list[str] = list(grouping.joins)
    if ctx.kategorie:                      # Filter braucht produkt + kategorie
        noetig += ["produkt", "kategorie"]
    # Reihenfolge erhalten, Duplikate entfernen (kategorie setzt produkt voraus)
    reihenfolge = ["produkt", "kategorie", "kunde"]
    extra_joins = "\n        ".join(
        JOINS[j] for j in reihenfolge if j in noetig)

    achse = f"{grouping.alias}.{grouping.column}"
    sortier = f"{grouping.alias}.{grouping.order_column}"

    sql = f"""
        SELECT {achse} AS achse, {agg}
        FROM fakt_verkauf f
        JOIN dim_zeit   z ON z.datum_id  = f.datum_id
        JOIN dim_region r ON r.region_id = f.region_id
        {extra_joins}
        {"WHERE " + " AND ".join(where) if where else ""}
        GROUP BY {achse}, {sortier}
        ORDER BY {sortier}
    """

    con = _connect()
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    labels = [str(r[0]) for r in rows]
    values: dict[str, list[float]] = {
        m: [float(r[j + 1] or 0.0) for r in rows] for j, m in enumerate(measures)
    }
    return labels, values
