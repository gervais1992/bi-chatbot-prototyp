"""Evaluation der Intent-Erkennung (Grundlage fuer Kapitel 6).

Spielt einen festen Satz von Nutzeraeusserungen gegen die drei Betriebsarten
und misst, wie zuverlaessig die beabsichtigte Aktion erkannt wird:

  regeln   -- nur das deterministische Regelwerk (Demo-Modus)
  llm      -- nur das Sprachmodell
  hybrid   -- Regeln zuerst, Modell als Rueckfallebene

Die Testfaelle sind nach Schwierigkeit gestaffelt:
  wortgetreu  -- Formulierung wie in der Dokumentation
  variiert    -- gleiche Absicht, andere Worte
  frei        -- umgangssprachlich, mit Tippfehlern

Aufruf:
    python3 evaluate.py                      # nur Regelwerk (ohne Modell)
    python3 evaluate.py --lokal              # zusaetzlich Ollama
    python3 evaluate.py --lokal --modell qwen3:8b
    python3 evaluate.py --csv ergebnisse.csv # Ergebnisse exportieren
"""
from __future__ import annotations

import argparse
import csv
import sys
import time

from bi_chatbot import interpreter as nlu
from bi_chatbot.state import AnalysisContext

# (Aeusserung, erwartete Aktion, Schwierigkeit)
TESTFAELLE: list[tuple[str, str, str]] = [
    # --- wortgetreu -------------------------------------------------------
    ("Welche Verkaufszahlen gibt es für das Jahr 2025?", "list_data", "wortgetreu"),
    ("Nimm bitte die Umsätze im Inland.", "set_filter", "wortgetreu"),
    ("Stelle den Gesamtumsatz nach Monaten dar.", "show_measure", "wortgetreu"),
    ("Verwende bitte Säulen statt Linien.", "set_chart_type", "wortgetreu"),
    ("Blende die Kosten als rote Linie ein.", "add_series", "wortgetreu"),
    ("Definiere eine neue Kennzahl „Gewinn“ = Umsatz − Kosten.", "define_kpi", "wortgetreu"),
    ("Gruppiere nach Quartalen.", "set_group_by", "wortgetreu"),
    ("Zeige nur Werktage.", "set_workday_filter", "wortgetreu"),
    ("Mach einen Jahresvergleich.", "set_group_by", "wortgetreu"),
    ("Gruppiere nach Produktkategorie.", "set_group_by", "wortgetreu"),
    ("Nur Software bitte.", "set_kategorie_filter", "wortgetreu"),
    ("Prognose für 2026", "set_prognose", "wortgetreu"),
    ("Unterschied zwischen Umsatz 2023 und 2024", "compare_periods", "wortgetreu"),

    # --- variiert ---------------------------------------------------------
    ("Was für Daten habt ihr für 2025?", "list_data", "variiert"),
    ("Beschränke die Auswertung auf das Inland", "set_filter", "variiert"),
    ("Zeig mir den Umsatz pro Monat", "show_measure", "variiert"),
    ("Lieber ein Balkendiagramm", "set_chart_type", "variiert"),
    ("Kannst du die Kosten dazunehmen?", "add_series", "variiert"),
    ("Leg eine Kennzahl Gewinn an: Umsatz minus Kosten", "define_kpi", "variiert"),
    ("Aufschlüsselung nach Quartal bitte", "set_group_by", "variiert"),
    ("Wochenenden interessieren mich nicht", "set_workday_filter", "variiert"),
    ("Wie haben sich die Jahre entwickelt?", "set_group_by", "variiert"),
    ("Umsatz je Kategorie anzeigen", "set_group_by", "variiert"),
    ("Beschränke auf Hardware", "set_kategorie_filter", "variiert"),
    ("Schätz mal den Umsatz für 2027", "set_prognose", "variiert"),
    ("Warum ist der Umsatz 2024 höher als 2023?", "compare_periods", "variiert"),
    ("Zeige den Umsatz von 2016", "inform", "variiert"),
    ("umsatzt pro monat zeigen", "show_measure", "variiert"),

    # --- frei / fehlerbehaftet -------------------------------------------
    ("umsätze inland nehmen", "set_filter", "frei"),
    ("mach säulen draus", "set_chart_type", "frei"),
    ("kosten bitte auch einblenden", "add_series", "frei"),
    ("quartalsweise gruppieren", "set_group_by", "frei"),
    ("nur werktage anzeigen bitte", "set_workday_filter", "frei"),
    ("umsatz der letzten 3 jahre", "show_measure", "frei"),
    ("hochrechnung 2026 machen", "set_prognose", "frei"),
    ("woher kommt die differenz 2023 2024", "compare_periods", "frei"),
]


def bewerte(strategie: str, client=None) -> tuple[list[dict], float]:
    """Spielt alle Testfaelle durch. Gibt Einzelergebnisse und Dauer zurueck."""
    ergebnisse = []
    start = time.time()
    for text, erwartet, stufe in TESTFAELLE:
        ctx = AnalysisContext()
        # Damit Folgebefehle sinnvoll sind, eine Reihe vorbereiten
        if erwartet in ("add_series", "set_chart_type", "set_group_by"):
            from bi_chatbot import semantic_layer as sem
            sem.show_measure(ctx, "umsatz")
        t0 = time.time()
        try:
            if strategie == "regeln":
                interp = nlu.interpret_rule_based(text, ctx)
            elif strategie == "llm":
                interp = nlu.interpret(text, ctx, client, regeln_zuerst=False)
            else:
                interp = nlu.interpret(text, ctx, client, regeln_zuerst=True)
            erkannt = interp.action
            fehler = ""
        except Exception as e:  # noqa: BLE001
            erkannt, fehler = "FEHLER", str(e)[:60]
        ergebnisse.append({
            "strategie": strategie, "stufe": stufe, "text": text,
            "erwartet": erwartet, "erkannt": erkannt,
            "korrekt": erkannt == erwartet,
            "sekunden": round(time.time() - t0, 2), "fehler": fehler,
        })
    return ergebnisse, time.time() - start


def bericht(alle: list[dict]) -> None:
    """Gibt Genauigkeit je Strategie und Schwierigkeitsstufe aus."""
    strategien = sorted({e["strategie"] for e in alle},
                        key=["regeln", "llm", "hybrid"].index)
    stufen = ["wortgetreu", "variiert", "frei"]

    print()
    print("=" * 72)
    print("GENAUIGKEIT DER INTENT-ERKENNUNG")
    print("=" * 72)
    kopf = f"{'Strategie':<10}" + "".join(f"{s:>14}" for s in stufen) + f"{'gesamt':>12}"
    print(kopf)
    print("-" * len(kopf))
    for strat in strategien:
        zeile = f"{strat:<10}"
        for stufe in stufen:
            teil = [e for e in alle if e["strategie"] == strat and e["stufe"] == stufe]
            if teil:
                q = sum(e["korrekt"] for e in teil) / len(teil) * 100
                zeile += f"{q:>12.0f} %"
            else:
                zeile += f"{'–':>14}"
        ges = [e for e in alle if e["strategie"] == strat]
        q = sum(e["korrekt"] for e in ges) / len(ges) * 100
        zeile += f"{q:>10.0f} %"
        print(zeile)

    print()
    print("Mittlere Antwortzeit je Aeusserung:")
    for strat in strategien:
        ges = [e for e in alle if e["strategie"] == strat]
        print(f"  {strat:<10} {sum(e['sekunden'] for e in ges) / len(ges):.2f} s")

    # Fehlerbild
    print()
    print("Nicht erkannte Faelle:")
    gab = False
    for strat in strategien:
        falsch = [e for e in alle if e["strategie"] == strat and not e["korrekt"]]
        for e in falsch:
            gab = True
            print(f"  [{strat}] „{e['text'][:46]}“")
            print(f"        erwartet {e['erwartet']}, erkannt {e['erkannt']}"
                  + (f" ({e['fehler']})" if e["fehler"] else ""))
    if not gab:
        print("  keine")


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluation der Intent-Erkennung")
    ap.add_argument("--lokal", action="store_true",
                    help="zusaetzlich lokales Modell (Ollama) auswerten")
    ap.add_argument("--modell", default="llama3.2:3b")
    ap.add_argument("--endpoint", default="http://localhost:11434/v1")
    ap.add_argument("--csv", help="Ergebnisse als CSV speichern")
    args = ap.parse_args()

    alle: list[dict] = []
    print(f"{len(TESTFAELLE)} Testfaelle")

    print("→ Strategie 'regeln' …")
    teil, dauer = bewerte("regeln")
    alle += teil
    print(f"   fertig in {dauer:.1f} s")

    if args.lokal:
        try:
            client = nlu.make_local_client(args.endpoint, args.modell)
        except Exception as e:  # noqa: BLE001
            print(f"\nLokales Modell nicht verfuegbar: {e}")
            print("Auswertung nur fuer das Regelwerk.")
            client = None
        if client:
            for strat in ("llm", "hybrid"):
                print(f"→ Strategie '{strat}' ({args.modell}) …")
                teil, dauer = bewerte(strat, client)
                alle += teil
                print(f"   fertig in {dauer:.1f} s")

    bericht(alle)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(alle[0].keys()))
            w.writeheader()
            w.writerows(alle)
        print(f"\nCSV geschrieben: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
