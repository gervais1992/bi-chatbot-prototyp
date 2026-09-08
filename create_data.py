"""Erzeugt die Demo-Datenbank (Sternschema) mit fiktiven, aber plausiblen Daten.

Modell siehe schema.sql. Erzeugt werden:
  dim_zeit, dim_region, dim_produkt, dim_kunde, fakt_verkauf
sowie die flache Sicht `sales` (Monatsebene).

Die Daten sind synthetisch, folgen aber bewusst realistischen Mustern:
  * Wachstumstrend ueber die Jahre
  * Saisonalitaet (schwacher Sommer, starkes Q4)
  * Wochentagseffekt (kaum Umsatz am Wochenende)
  * Segment- und Produkteffekte (Key Accounts kaufen groessere Mengen)
  * multiplikatives Rauschen

Reproduzierbar durch festen Zufallsstartwert (SEED).

Aufruf:  python create_data.py
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

# --- Parameter -----------------------------------------------------------
SEED = 42
JAHRE = (2023, 2024, 2025)     # drei volle Geschaeftsjahre
JAHRESWACHSTUM = 0.15          # +15 % pro Jahr
BASIS_POSITIONEN_PRO_TAG = 30  # mittlere Anzahl Auftragspositionen werktags

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "bi_demo.duckdb"

MONATE_KURZ = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
               "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
MONATE_LANG = ["Januar", "Februar", "März", "April", "Mai", "Juni",
               "Juli", "August", "September", "Oktober", "November", "Dezember"]
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Saisonfaktoren je Monat (Jan..Dez): Sommerloch, starkes Jahresende
SAISON = [0.88, 0.90, 1.00, 1.02, 1.05, 1.00,
          0.82, 0.78, 1.05, 1.10, 1.15, 1.28]

# Wochentagsfaktoren (Mo..So)
WOCHENTAG_FAKTOR = [1.05, 1.10, 1.08, 1.06, 0.95, 0.18, 0.06]

# --- Stammdaten ----------------------------------------------------------
REGIONEN = [
    # (region, land, vertriebsgebiet, gewicht)
    ("Inland", "Deutschland", "Nord", 3.0),
    ("Inland", "Deutschland", "Süd", 3.5),
    ("Inland", "Deutschland", "West", 3.2),
    ("Inland", "Deutschland", "Ost", 2.1),
    ("Ausland", "Österreich", "DACH", 1.4),
    ("Ausland", "Schweiz", "DACH", 1.3),
    ("Ausland", "Frankreich", "West-EU", 1.5),
    ("Ausland", "Niederlande", "West-EU", 1.2),
]

# Kategorien als eigene Dimension (Schneeflocken-Normalisierung von dim_produkt)
# (kategorie, kategorie_typ, marge_ziel in Prozent)
KATEGORIEN = [
    ("Hardware", "Physisch", 30.0),
    ("Software", "Digital", 75.0),
    ("Service", "Dienstleistung", 45.0),
]

PRODUKTE = [
    # (produkt, kategorie, listenpreis, stueckkosten, gewicht)
    ("Sensor-Modul S1", "Hardware", 149.00, 96.00, 2.6),
    ("Sensor-Modul S3", "Hardware", 289.00, 191.00, 1.8),
    ("Gateway G200", "Hardware", 749.00, 512.00, 1.1),
    ("Steuergerät C50", "Hardware", 1290.00, 890.00, 0.7),
    ("Analytics-Lizenz", "Software", 480.00, 96.00, 1.9),
    ("Dashboard-Lizenz", "Software", 260.00, 52.00, 2.2),
    ("Wartungsvertrag", "Service", 890.00, 480.00, 1.3),
    ("Inbetriebnahme", "Service", 1450.00, 910.00, 0.6),
]

BRANCHEN = ["Industrie", "Handel", "Logistik", "Energie",
            "Gesundheit", "Öffentlicher Sektor"]

# (segment, mengenfaktor, rabatt, gewicht)
SEGMENTE = [
    ("Key Account", 3.2, 0.14, 0.18),
    ("Mittelstand", 1.4, 0.07, 0.42),
    ("Klein", 0.7, 0.02, 0.40),
]

FIRMA_TEIL1 = ["Nord", "Alpen", "Rhein", "Elbe", "Donau", "Weser", "Main",
               "Isar", "Hansa", "Bavaria", "Saar", "Lausitz", "Baltic", "Vogel"]
FIRMA_TEIL2 = ["technik", "systems", "logistik", "werke", "industrie",
               "solutions", "digital", "handel", "energie", "consult"]
FIRMA_RECHTSFORM = ["GmbH", "AG", "GmbH & Co. KG", "SE"]


# --- Dimensionen ---------------------------------------------------------
def build_dim_zeit() -> pd.DataFrame:
    start = date(JAHRE[0], 1, 1)
    ende = date(JAHRE[-1], 12, 31)
    zeilen = []
    tag = start
    while tag <= ende:
        wt = tag.weekday()  # 0 = Montag
        zeilen.append({
            "datum_id": tag.year * 10000 + tag.month * 100 + tag.day,
            "datum": tag,
            "jahr": tag.year,
            "quartal": (tag.month - 1) // 3 + 1,
            "quartal_label": f"Q{(tag.month - 1) // 3 + 1}",
            "monat_nr": tag.month,
            "monat": MONATE_KURZ[tag.month - 1],
            "monat_lang": MONATE_LANG[tag.month - 1],
            "kalenderwoche": tag.isocalendar()[1],
            "wochentag_nr": wt + 1,
            "wochentag": WOCHENTAGE[wt],
            "ist_wochenende": wt >= 5,
        })
        tag += timedelta(days=1)
    return pd.DataFrame(zeilen)


def build_dim_region() -> pd.DataFrame:
    return pd.DataFrame([
        {"region_id": i + 1, "region": r, "land": l, "vertriebsgebiet": v}
        for i, (r, l, v, _w) in enumerate(REGIONEN)
    ])


def build_dim_kategorie() -> pd.DataFrame:
    return pd.DataFrame([
        {"kategorie_id": i + 1, "kategorie": k,
         "kategorie_typ": t, "marge_ziel": m}
        for i, (k, t, m) in enumerate(KATEGORIEN)
    ])


def build_dim_produkt() -> pd.DataFrame:
    """Produktdimension mit Fremdschluessel auf dim_kategorie."""
    kategorie_id = {k: i + 1 for i, (k, _t, _m) in enumerate(KATEGORIEN)}
    return pd.DataFrame([
        {"produkt_id": i + 1, "produkt": p, "kategorie_id": kategorie_id[k],
         "listenpreis": lp, "stueckkosten": sk}
        for i, (p, k, lp, sk, _w) in enumerate(PRODUKTE)
    ])


def build_dim_kunde(rng: random.Random, anzahl: int = 60) -> pd.DataFrame:
    region_gewichte = [w for *_r, w in REGIONEN]
    region_ids = list(range(1, len(REGIONEN) + 1))
    seg_namen = [s[0] for s in SEGMENTE]
    seg_gewichte = [s[3] for s in SEGMENTE]

    namen: set[str] = set()
    zeilen = []
    while len(zeilen) < anzahl:
        name = (f"{rng.choice(FIRMA_TEIL1)}{rng.choice(FIRMA_TEIL2)} "
                f"{rng.choice(FIRMA_RECHTSFORM)}")
        if name in namen:
            continue
        namen.add(name)
        zeilen.append({
            "kunde_id": len(zeilen) + 1,
            "kunde": name,
            "branche": rng.choice(BRANCHEN),
            "segment": rng.choices(seg_namen, weights=seg_gewichte)[0],
            "region_id": rng.choices(region_ids, weights=region_gewichte)[0],
        })
    return pd.DataFrame(zeilen)


# --- Faktentabelle -------------------------------------------------------
def build_fakt(rng: random.Random, dim_zeit: pd.DataFrame,
               dim_kunde: pd.DataFrame) -> pd.DataFrame:
    produkt_ids = list(range(1, len(PRODUKTE) + 1))
    produkt_gewichte = [p[4] for p in PRODUKTE]
    kunden = dim_kunde.to_dict("records")
    seg_info = {s[0]: (s[1], s[2]) for s in SEGMENTE}

    start_jahr = JAHRE[0]
    zeilen = []
    verkauf_id = 1

    for tag in dim_zeit.to_dict("records"):
        # Trend: exponentielles Wachstum ueber den gesamten Zeitraum
        jahre_seit_start = (tag["jahr"] - start_jahr) + (tag["monat_nr"] - 1) / 12
        trend = (1 + JAHRESWACHSTUM) ** jahre_seit_start

        faktor = (trend
                  * SAISON[tag["monat_nr"] - 1]
                  * WOCHENTAG_FAKTOR[tag["wochentag_nr"] - 1])

        # Anzahl Auftragspositionen an diesem Tag
        erwartet = BASIS_POSITIONEN_PRO_TAG * faktor
        anzahl = max(0, int(rng.gauss(erwartet, max(1.0, erwartet * 0.15))))

        for _ in range(anzahl):
            kunde = rng.choice(kunden)
            mengenfaktor, rabatt = seg_info[kunde["segment"]]
            p_idx = rng.choices(produkt_ids, weights=produkt_gewichte)[0] - 1
            _name, _kat, listenpreis, stueckkosten, _w = PRODUKTE[p_idx]

            # Menge: kleine Stueckzahlen, vom Segment skaliert
            basis_menge = rng.choices([1, 2, 3, 5, 8],
                                      weights=[40, 26, 18, 11, 5])[0]
            menge = max(1, int(round(basis_menge * mengenfaktor
                                     * rng.uniform(0.8, 1.2))))

            # Preis: Listenpreis abzueglich Segmentrabatt und kleiner Streuung
            preis = listenpreis * (1 - rabatt) * rng.uniform(0.97, 1.02)
            # Stueckkosten schwanken leicht (Beschaffung)
            kosten_je_stueck = stueckkosten * rng.uniform(0.96, 1.05)

            zeilen.append({
                "verkauf_id": verkauf_id,
                "datum_id": tag["datum_id"],
                "region_id": kunde["region_id"],
                "produkt_id": p_idx + 1,
                "kunde_id": kunde["kunde_id"],
                "menge": menge,
                "umsatz": round(menge * preis, 2),
                "kosten": round(menge * kosten_je_stueck, 2),
            })
            verkauf_id += 1

    return pd.DataFrame(zeilen)


# --- Aufbau --------------------------------------------------------------
def build(db_path: Path = DB_PATH, export_csv: bool = True) -> Path:
    rng = random.Random(SEED)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    dim_zeit = build_dim_zeit()
    dim_region = build_dim_region()
    dim_kategorie = build_dim_kategorie()
    dim_produkt = build_dim_produkt()
    dim_kunde = build_dim_kunde(rng)
    fakt = build_fakt(rng, dim_zeit, dim_kunde)

    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        for name, df in [("dim_zeit", dim_zeit), ("dim_region", dim_region),
                         ("dim_kategorie", dim_kategorie),
                         ("dim_produkt", dim_produkt), ("dim_kunde", dim_kunde),
                         ("fakt_verkauf", fakt)]:
            con.register("tmp_df", df)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM tmp_df")
            con.unregister("tmp_df")

        # Flache Kompatibilitaetssicht auf Monatsebene
        con.execute("""
            CREATE VIEW sales AS
            SELECT z.jahr, z.monat_nr, z.monat, r.region,
                   SUM(f.umsatz) AS umsatz,
                   SUM(f.kosten) AS kosten
            FROM fakt_verkauf f
            JOIN dim_zeit   z ON z.datum_id  = f.datum_id
            JOIN dim_region r ON r.region_id = f.region_id
            GROUP BY z.jahr, z.monat_nr, z.monat, r.region
        """)

        if export_csv:
            dim_zeit.to_csv(DATA_DIR / "dim_zeit.csv", index=False)
            dim_region.to_csv(DATA_DIR / "dim_region.csv", index=False)
            dim_kategorie.to_csv(DATA_DIR / "dim_kategorie.csv", index=False)
            dim_produkt.to_csv(DATA_DIR / "dim_produkt.csv", index=False)
            dim_kunde.to_csv(DATA_DIR / "dim_kunde.csv", index=False)
            fakt.to_csv(DATA_DIR / "fakt_verkauf.csv", index=False)
            con.execute(
                f"COPY (SELECT * FROM sales ORDER BY jahr, region, monat_nr) "
                f"TO '{DATA_DIR / 'sales_monatlich.csv'}' (HEADER, DELIMITER ',')"
            )

        print(f"Datenbank: {db_path}")
        print(f"  dim_zeit      {len(dim_zeit):>7} Zeilen")
        print(f"  dim_region    {len(dim_region):>7} Zeilen")
        print(f"  dim_kategorie {len(dim_kategorie):>7} Zeilen")
        print(f"  dim_produkt   {len(dim_produkt):>7} Zeilen")
        print(f"  dim_kunde     {len(dim_kunde):>7} Zeilen")
        print(f"  fakt_verkauf  {len(fakt):>7} Zeilen")
    finally:
        con.close()
    return db_path


if __name__ == "__main__":
    build()
