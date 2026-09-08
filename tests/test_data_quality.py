"""Tests zur Datenqualitaet und referentiellen Integritaet des Sternschemas.

Solche Pruefungen sind ein guter Baustein fuer Kapitel 6 (Evaluation):
sie zeigen, dass die synthetischen Daten konsistent und plausibel sind.
"""
from pathlib import Path

import duckdb
import pytest

DB = Path(__file__).resolve().parent.parent / "data" / "bi_demo.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        import create_data
        create_data.build()
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def test_alle_tabellen_vorhanden(con):
    tabellen = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    erwartet = {"dim_zeit", "dim_region", "dim_kategorie", "dim_produkt",
                "dim_kunde", "fakt_verkauf", "sales"}
    assert erwartet <= tabellen


def test_referentielle_integritaet(con):
    """Jeder Fremdschluessel in der Faktentabelle muss aufloesbar sein."""
    checks = [
        ("datum_id", "dim_zeit"),
        ("region_id", "dim_region"),
        ("produkt_id", "dim_produkt"),
        ("kunde_id", "dim_kunde"),
    ]
    for spalte, dim in checks:
        verwaist = con.execute(f"""
            SELECT COUNT(*) FROM fakt_verkauf f
            LEFT JOIN {dim} d ON d.{spalte} = f.{spalte}
            WHERE d.{spalte} IS NULL
        """).fetchone()[0]
        assert verwaist == 0, f"Verwaiste Schluessel in {spalte}"


def test_keine_nullwerte_in_kennzahlen(con):
    n = con.execute("""
        SELECT COUNT(*) FROM fakt_verkauf
        WHERE menge IS NULL OR umsatz IS NULL OR kosten IS NULL
    """).fetchone()[0]
    assert n == 0


def test_kennzahlen_positiv(con):
    n = con.execute("""
        SELECT COUNT(*) FROM fakt_verkauf
        WHERE menge <= 0 OR umsatz <= 0 OR kosten <= 0
    """).fetchone()[0]
    assert n == 0


def test_umsatz_groesser_kosten(con):
    """Der Deckungsbeitrag muss insgesamt positiv sein."""
    umsatz, kosten = con.execute(
        "SELECT SUM(umsatz), SUM(kosten) FROM fakt_verkauf").fetchone()
    assert umsatz > kosten


def test_zeitdimension_lueckenlos(con):
    """Pro Jahr muss jeder Kalendertag genau einmal vorkommen."""
    n_2025 = con.execute(
        "SELECT COUNT(*) FROM dim_zeit WHERE jahr = 2025").fetchone()[0]
    assert n_2025 == 365
    doppelt = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT datum_id FROM dim_zeit GROUP BY datum_id HAVING COUNT(*) > 1
        )""").fetchone()[0]
    assert doppelt == 0


def test_sales_sicht_stimmt_mit_fakten_ueberein(con):
    """Die flache Sicht darf keine Umsaetze verlieren oder erfinden."""
    fakt = con.execute("SELECT SUM(umsatz) FROM fakt_verkauf").fetchone()[0]
    sicht = con.execute("SELECT SUM(umsatz) FROM sales").fetchone()[0]
    assert abs(float(fakt) - float(sicht)) < 1.0


def test_saisonalitaet_dezember_stark(con):
    """Plausibilitaet: Dezember liegt ueber dem Jahresdurchschnitt."""
    rows = dict(con.execute("""
        SELECT monat_nr, SUM(umsatz) FROM sales WHERE jahr = 2025
        GROUP BY monat_nr
    """).fetchall())
    schnitt = sum(float(v) for v in rows.values()) / 12
    assert float(rows[12]) > schnitt


def test_wachstum_zwischen_den_jahren(con):
    u2024, u2025 = [float(con.execute(
        "SELECT SUM(umsatz) FROM sales WHERE jahr = ?", [j]).fetchone()[0])
        for j in (2024, 2025)]
    assert u2025 > u2024


def test_produkt_kategorie_fremdschluessel(con):
    """dim_produkt verweist korrekt auf dim_kategorie (Schneeflocken-Zweig)."""
    verwaist = con.execute("""
        SELECT COUNT(*) FROM dim_produkt p
        LEFT JOIN dim_kategorie k ON k.kategorie_id = p.kategorie_id
        WHERE k.kategorie_id IS NULL
    """).fetchone()[0]
    assert verwaist == 0


def test_jede_kategorie_hat_produkte(con):
    ohne = con.execute("""
        SELECT COUNT(*) FROM dim_kategorie k
        LEFT JOIN dim_produkt p ON p.kategorie_id = k.kategorie_id
        WHERE p.produkt_id IS NULL
    """).fetchone()[0]
    assert ohne == 0


def test_kategorie_join_liefert_alle_umsaetze(con):
    """Der Verbund ueber dim_kategorie verliert keine Umsaetze."""
    direkt = float(con.execute("SELECT SUM(umsatz) FROM fakt_verkauf").fetchone()[0])
    ueber_join = float(con.execute("""
        SELECT SUM(f.umsatz) FROM fakt_verkauf f
        JOIN dim_produkt p USING (produkt_id)
        JOIN dim_kategorie k USING (kategorie_id)
    """).fetchone()[0])
    assert abs(direkt - ueber_join) < 1.0


def test_mindestens_drei_geschaeftsjahre(con):
    """Der Datenbestand deckt mindestens drei volle Jahre ab."""
    jahre = [r[0] for r in con.execute(
        "SELECT DISTINCT jahr FROM dim_zeit ORDER BY jahr").fetchall()]
    assert len(jahre) >= 3
    # Jedes Jahr ist vollstaendig (365 bzw. 366 Tage)
    for j in jahre:
        tage = con.execute(
            "SELECT COUNT(*) FROM dim_zeit WHERE jahr = ?", [j]).fetchone()[0]
        assert tage in (365, 366)


def test_beide_regionen_in_jedem_jahr(con):
    """Inland und Ausland sind in jedem Jahr mit Umsaetzen vertreten."""
    rows = con.execute("""
        SELECT jahr, region, SUM(umsatz) FROM sales
        GROUP BY jahr, region
    """).fetchall()
    je_jahr: dict[int, set[str]] = {}
    for jahr, region, umsatz in rows:
        assert float(umsatz) > 0
        je_jahr.setdefault(jahr, set()).add(region)
    for jahr, regionen in je_jahr.items():
        assert {"Inland", "Ausland"} <= regionen, f"Region fehlt in {jahr}"
