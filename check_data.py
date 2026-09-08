"""Pruefbericht der Demo-Datenbank.

Prueft Struktur, Inhalt und Plausibilitaet des Sternschemas und gibt einen
lesbaren Bericht aus. Nach jeder Aenderung an den Daten erneut ausfuehren.

Aufruf:  python3 check_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).parent / "data" / "bi_demo.duckdb"

ERWARTETE_TABELLEN = {
    "dim_zeit", "dim_region", "dim_kategorie", "dim_produkt", "dim_kunde",
    "fakt_verkauf", "sales",
}

# (Spalte in fakt_verkauf, Dimensionstabelle)
FREMDSCHLUESSEL = [
    ("datum_id", "dim_zeit"),
    ("region_id", "dim_region"),
    ("produkt_id", "dim_produkt"),
    ("kunde_id", "dim_kunde"),
]

OK = "  OK  "
FEHLER = " FEHLER "
WARNUNG = " HINWEIS"

fehler_gesamt = 0


def titel(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))


def pruefe(bedingung: bool, beschreibung: str, detail: str = "") -> bool:
    """Gibt eine Pruefzeile aus und zaehlt Fehler."""
    global fehler_gesamt
    marke = OK if bedingung else FEHLER
    if not bedingung:
        fehler_gesamt += 1
    zeile = f"[{marke}] {beschreibung}"
    if detail:
        zeile += f"  ({detail})"
    print(zeile)
    return bedingung


def main() -> int:
    print("=" * 68)
    print("PRUEFBERICHT DER DEMO-DATENBANK")
    print("=" * 68)

    if not DB_PATH.exists():
        print(f"\nDatenbank nicht gefunden: {DB_PATH}")
        print("Bitte zuerst ausfuehren:  python3 create_data.py")
        return 1

    groesse_mb = DB_PATH.stat().st_size / 1_048_576
    print(f"\nDatei: {DB_PATH.name}  ({groesse_mb:.2f} MB)")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # --- 1. Struktur ------------------------------------------------
        titel("1. Struktur")
        vorhanden = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        for tab in sorted(ERWARTETE_TABELLEN):
            pruefe(tab in vorhanden, f"Tabelle/Sicht '{tab}' vorhanden")
        unerwartet = vorhanden - ERWARTETE_TABELLEN
        if unerwartet:
            print(f"[{WARNUNG}] Zusaetzliche Objekte: {', '.join(sorted(unerwartet))}")

        # --- 2. Fuellstand ----------------------------------------------
        titel("2. Fuellstand")
        for tab in ["dim_zeit", "dim_region", "dim_kategorie", "dim_produkt",
                    "dim_kunde", "fakt_verkauf"]:
            if tab not in vorhanden:
                continue
            n = con.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]
            pruefe(n > 0, f"{tab:<14} enthaelt Daten", f"{n:,} Zeilen".replace(",", "."))

        # --- 3. Referentielle Integritaet -------------------------------
        titel("3. Referentielle Integritaet")
        for spalte, dim in FREMDSCHLUESSEL:
            verwaist = con.execute(f"""
                SELECT COUNT(*) FROM fakt_verkauf f
                LEFT JOIN {dim} d ON d.{spalte} = f.{spalte}
                WHERE d.{spalte} IS NULL
            """).fetchone()[0]
            pruefe(verwaist == 0,
                   f"Alle {spalte} verweisen auf {dim}",
                   "keine verwaisten Schluessel" if verwaist == 0
                   else f"{verwaist} verwaist")

        verwaist_kat = con.execute("""
            SELECT COUNT(*) FROM dim_produkt p
            LEFT JOIN dim_kategorie k ON k.kategorie_id = p.kategorie_id
            WHERE k.kategorie_id IS NULL
        """).fetchone()[0]
        pruefe(verwaist_kat == 0,
               "Alle kategorie_id verweisen auf dim_kategorie",
               "keine verwaisten Schluessel" if verwaist_kat == 0
               else f"{verwaist_kat} verwaist")

        # --- 4. Datenqualitaet ------------------------------------------
        titel("4. Datenqualitaet")
        nullwerte = con.execute("""
            SELECT COUNT(*) FROM fakt_verkauf
            WHERE menge IS NULL OR umsatz IS NULL OR kosten IS NULL
        """).fetchone()[0]
        pruefe(nullwerte == 0, "Keine NULL-Werte in den Kennzahlen")

        negativ = con.execute("""
            SELECT COUNT(*) FROM fakt_verkauf
            WHERE menge <= 0 OR umsatz <= 0 OR kosten <= 0
        """).fetchone()[0]
        pruefe(negativ == 0, "Alle Kennzahlen positiv")

        dubletten = con.execute("""
            SELECT COUNT(*) FROM (
                SELECT verkauf_id FROM fakt_verkauf
                GROUP BY verkauf_id HAVING COUNT(*) > 1)
        """).fetchone()[0]
        pruefe(dubletten == 0, "Keine doppelten Primaerschluessel")

        tage = con.execute(
            "SELECT COUNT(*) FROM dim_zeit WHERE jahr = 2025").fetchone()[0]
        pruefe(tage == 365, "Zeitdimension 2025 lueckenlos", f"{tage} Tage")

        # --- 5. Konsistenz der Sicht ------------------------------------
        titel("5. Konsistenz der Sicht 'sales'")
        u_fakt = float(con.execute(
            "SELECT SUM(umsatz) FROM fakt_verkauf").fetchone()[0])
        u_sicht = float(con.execute("SELECT SUM(umsatz) FROM sales").fetchone()[0])
        pruefe(abs(u_fakt - u_sicht) < 1.0,
               "Sicht 'sales' stimmt mit der Faktentabelle ueberein",
               f"Differenz {abs(u_fakt - u_sicht):.2f} EUR")

        # --- 6. Fachliche Plausibilitaet --------------------------------
        titel("6. Fachliche Plausibilitaet")
        u24, u25 = [float(con.execute(
            "SELECT COALESCE(SUM(umsatz), 0) FROM sales WHERE jahr = ?",
            [j]).fetchone()[0]) for j in (2024, 2025)]
        pruefe(u25 > u24, "Umsatzwachstum 2024 -> 2025",
               f"{u24/1e6:.2f} -> {u25/1e6:.2f} Mio EUR "
               f"(+{(u25/u24 - 1)*100:.1f} %)" if u24 else "")

        gewinn = float(con.execute(
            "SELECT SUM(umsatz) - SUM(kosten) FROM fakt_verkauf").fetchone()[0])
        pruefe(gewinn > 0, "Gesamtgewinn positiv",
               f"{gewinn/1e6:.2f} Mio EUR, Marge {100*gewinn/u_fakt:.1f} %")

        regionen = [r[0] for r in con.execute(
            "SELECT DISTINCT region FROM sales ORDER BY region").fetchall()]
        pruefe({"Inland", "Ausland"} <= set(regionen),
               "Regionen Inland und Ausland vorhanden", ", ".join(regionen))

        monate = con.execute(
            "SELECT COUNT(DISTINCT monat_nr) FROM sales WHERE jahr = 2025"
        ).fetchone()[0]
        pruefe(monate == 12, "Alle 12 Monate in 2025 belegt", f"{monate} Monate")

        # --- 7. Inhaltliche Uebersicht ----------------------------------
        titel("7. Monatsuebersicht Inland 2025 (Tsd. EUR)")
        zeilen = con.execute("""
            SELECT monat, umsatz/1000, kosten/1000, (umsatz - kosten)/1000
            FROM sales WHERE jahr = 2025 AND region = 'Inland'
            ORDER BY monat_nr
        """).fetchall()
        print(f"{'Monat':<7}{'Umsatz':>9}{'Kosten':>9}{'Gewinn':>9}   Verlauf")
        maximum = max((float(r[1]) for r in zeilen), default=1)
        for monat, u, k, g in zeilen:
            balken = "#" * int(float(u) / maximum * 28)
            print(f"{monat:<7}{float(u):>9.1f}{float(k):>9.1f}"
                  f"{float(g):>9.1f}   {balken}")

        titel("8. Verteilung nach Produktkategorie")
        for kat, umsatz, marge in con.execute("""
            SELECT k.kategorie, SUM(f.umsatz)/1000,
                   100*(SUM(f.umsatz) - SUM(f.kosten))/SUM(f.umsatz)
            FROM fakt_verkauf f
            JOIN dim_produkt p USING (produkt_id)
            JOIN dim_kategorie k USING (kategorie_id)
            GROUP BY k.kategorie ORDER BY 2 DESC
        """).fetchall():
            print(f"  {kat:<12}{float(umsatz):>10.0f} Tsd. EUR"
                  f"   Marge {float(marge):>5.1f} %")

    finally:
        con.close()

    # --- Ergebnis -------------------------------------------------------
    print()
    print("=" * 68)
    if fehler_gesamt == 0:
        print("ERGEBNIS: Alle Pruefungen bestanden. "
              "Die Datenbank ist einsatzbereit.")
    else:
        print(f"ERGEBNIS: {fehler_gesamt} Pruefung(en) fehlgeschlagen.")
        print("Zum Neuaufbau der Datenbank:  python3 create_data.py")
    print("=" * 68)
    return 0 if fehler_gesamt == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
