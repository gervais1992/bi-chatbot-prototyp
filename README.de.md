# BI-Chatbot – Prototyp

Prototyp eines **lernfähigen Chatbots zur interaktiven Erstellung von
Business-Intelligence-Auswertungen**. Der Nutzer erstellt im Dialog eine
Auswertung, ändert Diagrammtypen, blendet Reihen ein und definiert Kennzahlen
zur Laufzeit – so wie im Beispieldialog des Professors.

## Stack

| Schicht          | Technologie                                   |
|------------------|-----------------------------------------------|
| UI               | Streamlit                                     |
| NLU              | LLM via Instructor (Cloud **oder** lokal/Ollama) + regelbasierter Demo-Modus |
| Semantische Schicht | eigenes Python-Modul (Kennzahlen, KPIs)    |
| Datenzugriff     | DuckDB                                         |
| Visualisierung   | Plotly                                         |

Das LLM erzeugt **kein SQL**, sondern nur strukturierte Kommandos gegen ein
kontrolliertes Vokabular (Function-Calling-Prinzip). Das ist sicher, testbar
und entspricht dem Komponentenmodell aus Kapitel 4.

## Schnellstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python create_data.py        # erzeugt data/bi_demo.duckdb (optional, geschieht sonst automatisch)
streamlit run app.py
```

Die App öffnet im Browser. Im **Demo-Modus** (Standard, kein API-Schlüssel
nötig) den Beispieldialog Schritt für Schritt eingeben. Für den **LLM-Modus**
in der Seitenleiste Anbieter, Modell und API-Schlüssel eintragen.

> Hinweis: Die Modellnamen (`claude-sonnet-5` o. ä.) sind Beispiele – bitte an
> die aktuell verfügbaren Modelle Ihres Anbieters anpassen.

## Lokales Modell (Ollama) – Datensouveränität

Der **Lokal-Modus** lässt das NLU-Modul auf einem selbst gehosteten,
open-weight Modell laufen. Die Daten verlassen den Rechner nicht, es fallen
keine API-Kosten an und es funktioniert offline.

```bash
# 1. Ollama installieren:  https://ollama.com
# 2. Ein Modell ziehen (function-calling-/JSON-fähig):
ollama pull qwen2.5          # Alternativen: llama3.1, mistral, gpt-oss
# 3. Ollama läuft danach als Dienst unter http://localhost:11434
streamlit run app.py
```

In der Seitenleiste **„Lokal (Ollama)“** wählen, Modellname eintragen
(z. B. `qwen2.5`) und auf **Verbinden** klicken.

Technisch nutzt der Prototyp die OpenAI-kompatible API von Ollama zusammen mit
`instructor` im `Mode.JSON`. Dieser Modus erzwingt gültiges JSON per
Schema und ist bei lokalen Modellen zuverlässiger als deren uneinheitliches
Function-Calling. Kleinere Modelle können bei komplexen Formulierungen
gelegentlich danebenliegen – daher `max_retries` und ein Gesamt-`timeout`.

> Der Vergleich **Cloud- vs. Lokal-Modus** (Genauigkeit der Intent-Erkennung,
> Latenz, Datenschutz) ist ein sehr guter Baustein für die Evaluation (Kap. 6).

## Datenmodell (Sternschema)

Die Demo-Datenbank folgt einem **Sternschema** nach Kimball – dem Standard der
dimensionalen Modellierung in der Business Intelligence. Die vollständige DDL
mit Kommentaren steht in [`schema.sql`](schema.sql).

```
        dim_zeit                    dim_region
             \                        /
              \                      /
               +--- fakt_verkauf ---+
              /                      \
             /                        \
        dim_produkt                 dim_kunde
```

**Granularität der Faktentabelle:** eine Auftragsposition
= *ein Tag × ein Produkt × ein Kunde*. Alle Aggregationen (Monat, Quartal,
Region, Kategorie) entstehen zur Abfragezeit per `GROUP BY`.

**Nur additive Basiskennzahlen** (`menge`, `umsatz`, `kosten`) werden
gespeichert. Abgeleitete Kennzahlen wie *Gewinn* werden bewusst **nicht**
materialisiert, sondern zur Laufzeit in der semantischen Schicht berechnet –
genau das ist die Grundlage für die dialogbasierte KPI-Definition (Kap. 4).

Zusätzlich existiert die flache Sicht `sales` (Monatsebene), die der Prototyp
für den Beispieldialog nutzt.

### Erzeugung der fiktiven Daten

```bash
python create_data.py
```

Die Daten sind synthetisch, folgen aber bewusst realistischen Mustern, damit
die Diagramme im Dialog aussagekräftig sind:

| Effekt | Umsetzung |
|---|---|
| Wachstumstrend | +18 % pro Jahr, exponentiell über den Zeitraum |
| Saisonalität | Sommerloch (Jul/Aug), starkes Q4, Dezemberspitze |
| Wochentagseffekt | Wochenenden nahezu ohne Umsatz |
| Segmenteffekt | Key Accounts kaufen größere Mengen, erhalten Rabatt |
| Produkteffekt | Software hohe Marge, Hardware niedrige Marge |
| Rauschen | multiplikative Streuung bei Menge, Preis und Stückkosten |

Der Zufallsstartwert ist fest (`SEED = 42`), die Erzeugung also
**reproduzierbar** – wichtig für die Nachvollziehbarkeit der Evaluation.
Zeitraum, Wachstum und Volumen lassen sich oben in `create_data.py` anpassen.

Alle Tabellen werden zusätzlich als CSV nach `data/` exportiert.

## Tests

```bash
pytest -q
```

Die Tests spielen u. a. den kompletten Beispieldialog durch und prüfen die
Laufzeit-Definition der Kennzahl „Gewinn“.

## Projektstruktur

```
app.py                    Streamlit-Oberfläche
create_data.py            Erzeugt Sternschema + fiktive Daten
schema.sql                Dokumentiertes Datenmodell (DDL)
bi_chatbot/
  state.py                Dialog-/Analysezustand (Kontext, "lernfähig")
  semantic_layer.py       Kennzahlen, KPIs, Kommando-Ausführung
  schema.py               Pydantic-Ausgabeschema des NLU-Moduls
  interpreter.py          LLM- und Demo-Modus + Ausführung
  db.py                   DuckDB-Zugriff (Basiskennzahlen)
  charts.py               Plotly-Diagramme
data/
  bi_demo.duckdb          Demo-Datenbank (Sternschema, 2024–2025)
  *.csv                   alle Tabellen zur Inspektion
tests/
  test_semantic.py        Dialog- und KPI-Logik
  test_data_quality.py    Integrität und Plausibilität der Daten
```

## Zuordnung zur Gliederung

- **Kap. 4 Konzeption** – `schema.sql` (Datenmodell), `semantic_layer.py`, `state.py`, `schema.py`
- **Kap. 5 Implementierung** – `app.py`, `interpreter.py`, `db.py`, `charts.py`
- **Kap. 6 Evaluation** – `tests/`

## Nächste Schritte (Ideen für Erweiterungen)

- Dimensionen Produkt/Kunde auch im Dialog nutzbar machen
  („Umsatz je Produktkategorie“, „nur Key Accounts“)
- Weitere Aggregationsebenen (Quartal, Kalenderwoche)
- Mehrere Aktionen pro Nachricht
- Persistenz des Dialogverlaufs
- Vergleich LLM-Modus vs. Demo-Modus in der Evaluation
