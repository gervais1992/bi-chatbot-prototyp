-- ---------------------------------------------------------------------------
-- Sternschema (Star Schema) des BI-Chatbot-Prototyps
--
-- Modellierung nach Kimball: eine zentrale Faktentabelle mit additiven
-- Kennzahlen, umgeben von denormalisierten Dimensionstabellen.
-- Granularitaet der Faktentabelle: eine Auftragsposition
--   = ein Tag x ein Produkt x ein Kunde.
--
-- Diese Datei dokumentiert das Modell (Kapitel 4). Erzeugt wird die Datenbank
-- durch  python create_data.py
-- ---------------------------------------------------------------------------

-- === Dimensionen ==========================================================

-- Zeitdimension: eine Zeile pro Kalendertag.
-- Vorberechnete Attribute erlauben Aggregationen ohne Datumsfunktionen.
CREATE TABLE dim_zeit (
    datum_id      INTEGER PRIMARY KEY,   -- YYYYMMDD, z.B. 20250315
    datum         DATE    NOT NULL,
    jahr          INTEGER NOT NULL,
    quartal       INTEGER NOT NULL,      -- 1..4
    quartal_label VARCHAR NOT NULL,      -- 'Q1'
    monat_nr      INTEGER NOT NULL,      -- 1..12
    monat         VARCHAR NOT NULL,      -- 'Jan'
    monat_lang    VARCHAR NOT NULL,      -- 'Januar'
    kalenderwoche INTEGER NOT NULL,
    wochentag_nr  INTEGER NOT NULL,      -- 1 = Montag
    wochentag     VARCHAR NOT NULL,      -- 'Mo'
    ist_wochenende BOOLEAN NOT NULL
);

-- Regionsdimension: fachliche Hierarchie Region > Land > Vertriebsgebiet.
CREATE TABLE dim_region (
    region_id        INTEGER PRIMARY KEY,
    region           VARCHAR NOT NULL,   -- 'Inland' | 'Ausland'
    land             VARCHAR NOT NULL,   -- 'Deutschland', 'Frankreich', ...
    vertriebsgebiet  VARCHAR NOT NULL    -- 'Nord', 'Sued', 'West', 'Ost'
);

-- Kategoriedimension (normalisierte Auslagerung aus dim_produkt).
-- Hinweis: durch diese Auslagerung wird aus dem reinen Sternschema formal ein
-- Schneeflockenschema (Snowflake). Vorteil: Kategorieattribute werden nur
-- einmal gepflegt; Nachteil: eine zusaetzliche Verbundoperation je Abfrage.
CREATE TABLE dim_kategorie (
    kategorie_id  INTEGER PRIMARY KEY,
    kategorie     VARCHAR NOT NULL,      -- 'Hardware' | 'Software' | 'Service'
    kategorie_typ VARCHAR NOT NULL,      -- 'Physisch' | 'Digital' | 'Dienstleistung'
    marge_ziel    DECIMAL(5,2) NOT NULL  -- Zielmarge in Prozent
);

-- Produktdimension.
CREATE TABLE dim_produkt (
    produkt_id   INTEGER PRIMARY KEY,
    produkt      VARCHAR NOT NULL,
    kategorie_id INTEGER NOT NULL REFERENCES dim_kategorie(kategorie_id),
    listenpreis  DECIMAL(10,2) NOT NULL, -- EUR je Einheit
    stueckkosten DECIMAL(10,2) NOT NULL  -- EUR je Einheit
);

-- Kundendimension.
CREATE TABLE dim_kunde (
    kunde_id  INTEGER PRIMARY KEY,
    kunde     VARCHAR NOT NULL,
    branche   VARCHAR NOT NULL,          -- 'Industrie', 'Handel', ...
    segment   VARCHAR NOT NULL,          -- 'Key Account' | 'Mittelstand' | 'Klein'
    region_id INTEGER NOT NULL REFERENCES dim_region(region_id)
);

-- === Faktentabelle ========================================================
-- Nur additive Basiskennzahlen. Abgeleitete Kennzahlen (z.B. Gewinn) werden
-- BEWUSST NICHT gespeichert, sondern zur Laufzeit in der semantischen
-- Schicht berechnet -- vgl. Kapitel 4 (Definition von Kennzahlen).
CREATE TABLE fakt_verkauf (
    verkauf_id INTEGER PRIMARY KEY,
    datum_id   INTEGER NOT NULL REFERENCES dim_zeit(datum_id),
    region_id  INTEGER NOT NULL REFERENCES dim_region(region_id),
    produkt_id INTEGER NOT NULL REFERENCES dim_produkt(produkt_id),
    kunde_id   INTEGER NOT NULL REFERENCES dim_kunde(kunde_id),
    menge      INTEGER NOT NULL,
    umsatz     DECIMAL(12,2) NOT NULL,   -- menge * effektiver Preis
    kosten     DECIMAL(12,2) NOT NULL    -- menge * Stueckkosten
);

-- === Kompatibilitaetssicht ================================================
-- Flache Sicht auf Monatsebene. Haelt den bestehenden Prototyp-Code lauffaehig
-- und dient als einfaches Beispiel fuer eine aggregierte Auswertung.
CREATE VIEW sales AS
SELECT
    z.jahr,
    z.monat_nr,
    z.monat,
    r.region,
    SUM(f.umsatz) AS umsatz,
    SUM(f.kosten) AS kosten
FROM fakt_verkauf f
JOIN dim_zeit   z ON z.datum_id  = f.datum_id
JOIN dim_region r ON r.region_id = f.region_id
GROUP BY z.jahr, z.monat_nr, z.monat, r.region;
