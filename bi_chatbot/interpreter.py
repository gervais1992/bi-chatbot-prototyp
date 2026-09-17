"""NLU-Modul: Nachricht -> strukturierte Interpretation -> Zustandsaenderung.

Zwei Betriebsarten:
  * LLM-Modus (interpret_llm): nutzt ein Sprachmodell via Instructor und gibt
    ein `Interpretation`-Objekt zurueck. Provider-agnostisch aufgebaut.
  * Demo-Modus (interpret_rule_based): einfache Schluesselwort-Regeln, die den
    Beispieldialog des Professors ohne API-Schluessel abspielen.

`apply` fuehrt die Interpretation gegen die semantische Schicht aus.
"""
from __future__ import annotations

from . import semantic_layer as sem
from .db import available_regions
from .schema import Interpretation
from .state import AnalysisContext

SYSTEM_PROMPT = """Du bist das NLU-Modul eines BI-Chatbots. Der Nutzer erstellt
im Dialog interaktiv Auswertungen. Uebersetze jede Nachricht in genau EINE
strukturierte Aktion aus dem erlaubten Vokabular.

REGELN fuer das Feld `reply`:
1. Bestaetige NUR die ausgefuehrte Aktion. Hoechstens EIN kurzer Satz.
2. Nenne NIEMALS konkrete Zahlen, Betraege oder Datenwerte. Du kennst die
   Daten nicht -- sie stehen im Diagramm. Schreibe nie "Der Umsatz betraegt ...".
3. Stelle keine Rueckfragen und kuendige nichts an. Schreibe einen
   vollstaendigen Satz mit Punkt am Ende.
4. Erfinde keine Kennzahlen ausserhalb des Vokabulars. Nutze fuer `measure`,
   `series_key` und `region` AUSSCHLIESSLICH die Schluessel aus dem Kontext
   (z.B. "umsatz", "kosten", "inland") -- exakt so geschrieben, klein.

5. Wenn noch KEIN Diagramm vorhanden ist und der Nutzer eine Kennzahl nennt
   (z.B. "Umsätze", "Kosten"), waehle IMMER action=show_measure -- nur so
   entsteht ein Diagramm. `set_filter` allein erzeugt kein Diagramm.
6. Behaupte nie, ein Diagramm zeige etwas, wenn keines vorhanden ist.
7. Nennt der Nutzer ein Jahr, das nicht im Datenbestand liegt (siehe
   "Verfuegbare Jahre" im Kontext), waehle action=inform und sage klar, dass
   dafuer keine Daten vorliegen. Erfinde niemals Daten fuer solche Jahre.

BEISPIELE:
Nutzer: "Welche Verkaufszahlen gibt es fuer 2025?"
-> action=list_data, reply="Es gibt Umsätze für Inland und Ausland."

Nutzer: "Umsätze für 2025"   (noch kein Diagramm vorhanden)
-> action=show_measure, measure=umsatz, jahr=2025, reply="Hier ist der Umsatzverlauf."

Nutzer: "Zeig mir den Umsatz pro Quartal"
-> action=set_group_by, group_by=quartal, reply="Die Auswertung ist jetzt nach Quartalen gruppiert."

Nutzer: "Nimm bitte das Inland"
-> action=set_filter, region=inland, reply="Ok, ich filtere auf das Inland."

Nutzer: "Wie hoch war der Umsatz?"
-> action=none, reply="Die Werte sehen Sie im Diagramm rechts."

Nutzer: "Zeige den Umsatz von 2016"   (2016 liegt nicht im Datenbestand)
-> action=inform, reply="Für 2016 liegen keine Daten vor."

Kontext:
{context}
"""


# --- LLM-Modus -----------------------------------------------------------
def interpret_llm(message: str, ctx: AnalysisContext, client) -> Interpretation:
    """Erwartet einen mit `instructor` gepatchten Client (siehe make_*_client)."""
    system = SYSTEM_PROMPT.format(context=sem.describe_for_prompt(ctx))
    extra = getattr(client, "_bi_kwargs", {})
    interp = client.chat.completions.create(
        model=client._bi_model,                      # im Client-Factory gesetzt
        response_model=Interpretation,
        max_tokens=600,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
        **extra,
    )
    # Kleine lokale Modelle liefern gelegentlich abgeschnittene oder
    # erfundene Antworttexte -> deterministisch absichern.
    return sanitize(interp, ctx)


def make_client(api_key: str, provider: str = "anthropic",
                model: str = "claude-sonnet-5"):
    """Baut einen Instructor-Client fuer eine Cloud-API. Nur Beispiel-Modellnamen
    -- bitte an die aktuell verfuegbaren Modelle anpassen."""
    import instructor
    if provider == "anthropic":
        from anthropic import Anthropic
        client = instructor.from_anthropic(Anthropic(api_key=api_key))
    else:  # openai
        from openai import OpenAI
        client = instructor.from_openai(OpenAI(api_key=api_key))
    client._bi_model = model
    client._bi_kwargs = {"max_retries": 2}
    return client


def make_local_client(base_url: str = "http://localhost:11434/v1",
                      model: str = "llama3.2:3b"):
    """Baut einen Instructor-Client fuer ein LOKALES Modell via Ollama.

    Ollama stellt eine OpenAI-kompatible API bereit. Wir nutzen daher den
    OpenAI-Client mit lokaler base_url und `Mode.JSON`, weil das Function-Calling
    lokaler Modelle uneinheitlich ist, JSON-Ausgabe aber zuverlaessig funktioniert.
    Daten verlassen den Rechner nicht.

    Wirft eine Ausnahme, wenn Ollama nicht erreichbar ist oder das Modell fehlt --
    sonst wuerde die Oberflaeche faelschlich "verbunden" melden.
    """
    import instructor
    from openai import OpenAI

    roh = OpenAI(base_url=base_url, api_key="ollama")  # Schluessel wird ignoriert

    # Erreichbarkeit und Modellverfuegbarkeit tatsaechlich pruefen
    try:
        verfuegbar = [m.id for m in roh.models.list().data]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Ollama ist unter {base_url} nicht erreichbar. Laeuft der Dienst? ({e})"
        ) from e

    if model not in verfuegbar and not any(v.startswith(model) for v in verfuegbar):
        raise RuntimeError(
            f"Das Modell „{model}“ ist nicht installiert. "
            f"Verfuegbar: {', '.join(verfuegbar) or 'keine'}. "
            f"Nachziehen mit: ollama pull {model}"
        )

    client = instructor.from_openai(roh, mode=instructor.Mode.JSON)
    client._bi_model = model
    # Lokale Modelle brauchen mehr Wiederholungen und ein Gesamt-Timeout.
    client._bi_kwargs = {"max_retries": 3, "timeout": 60.0}
    return client


# --- Demo-Modus (regelbasiert, ohne API) ---------------------------------
def interpret_rule_based(message: str, ctx: AnalysisContext) -> Interpretation:
    m = message.lower()

    if "verkaufszahl" in m or ("welche" in m and "gibt" in m):
        regionen = ", ".join(available_regions(ctx.jahr))
        return Interpretation(action="list_data",
                              reply=f"Es gibt Umsätze für: {regionen}. Welche möchten Sie?")

    if "inland" in m and ("nimm" in m or "nehme" in m or "wähle" in m or "bitte" in m):
        return Interpretation(action="set_filter", region="inland",
                              reply="Ok, Umsätze im Inland für das Jahr 2025.")
    if "ausland" in m and ("nimm" in m or "nehme" in m or "wähle" in m):
        return Interpretation(action="set_filter", region="ausland",
                              reply="Ok, Umsätze im Ausland für das Jahr 2025.")

    # --- Zeitachse wechseln ---
    if "quartal" in m:
        return Interpretation(action="set_group_by", group_by="quartal",
                              reply="Die Auswertung ist jetzt nach Quartalen gruppiert.")
    if "kalenderwoche" in m or " kw" in m or "wochenweise" in m:
        return Interpretation(action="set_group_by", group_by="kalenderwoche",
                              reply="Die Auswertung ist jetzt nach Kalenderwochen gruppiert.")
    if "wochentag" in m:
        return Interpretation(action="set_group_by", group_by="wochentag",
                              reply="Die Auswertung ist jetzt nach Wochentagen gruppiert.")
    if ("jahr" in m and ("vergleich" in m or "nach jahr" in m or "pro jahr" in m)) \
            or "jahresvergleich" in m:
        return Interpretation(action="set_group_by", group_by="jahr",
                              reply="Jahresvergleich: die Auswertung ist nach Jahren gruppiert.")
    if "monat" in m and ("nach" in m or "pro" in m or "gruppier" in m) \
            and "umsatz" not in m and "kosten" not in m:
        return Interpretation(action="set_group_by", group_by="monat",
                              reply="Die Auswertung ist jetzt nach Monaten gruppiert.")

    # --- Prognose ---
    import re as _re2
    jahre_im_text = [int(j) for j in _re2.findall(r"\b(19\d{2}|20\d{2})\b", m)]

    # --- Zielwertsuche: "Was haette ich tun muessen, um X zu erreichen?" ---
    if len(jahre_im_text) >= 2 and any(
            w in m for w in ("erreichen", "erreicht", "nötig", "noetig",
                             "tun müssen", "tun muessen", "hätte", "haette",
                             "zielwert", "was wäre", "was waere")):
        kennzahl = "kosten" if "kosten" in m and "umsatz" not in m else "umsatz"
        # Muster: "<Ziel> bereits im Jahr <Basis>" -> das spaetere Jahr ist Ziel
        ziel, basis = max(jahre_im_text[:2]), min(jahre_im_text[:2])
        return Interpretation(action="goal_seek", basis_jahr=basis,
                              ziel_jahr=ziel, measure=kennzahl,
                              chart_type="bar",
                              reply="Zielwertsuche berechnet.")

    # --- Abweichungsanalyse: "Unterschied zwischen 2023 und 2024" ---
    if len(jahre_im_text) >= 2 and any(
            w in m for w in ("unterschied", "differenz", "vergleich", "warum",
                             "woher", "abweichung", "veränderung", "veraenderung")):
        kennzahl = "kosten" if "kosten" in m and "umsatz" not in m else "umsatz"
        return Interpretation(action="compare_periods",
                              vergleich_jahre=jahre_im_text[:2],
                              measure=kennzahl, chart_type="bar",
                              reply="Abweichungsanalyse berechnet.")

    # Nennt der Nutzer ein Jahr ohne Datenbestand, darf das nicht stillschweigend
    # ignoriert werden -- sonst zeigt das Diagramm ein anderes Jahr als gefragt.
    if jahre_im_text and not any(w in m for w in ("prognose", "vorhersage",
                                                 "schätz", "schaetz",
                                                 "hochrechnung", "forecast")):
        from .db import available_years
        vorhanden = available_years()
        fehlend = [j for j in jahre_im_text if j not in vorhanden]
        if fehlend and vorhanden:
            jahr = fehlend[0]
            return Interpretation(
                action="inform",
                reply=(f"Für {jahr} liegen keine Daten vor. Verfügbar: "
                       f"{vorhanden[0]}–{vorhanden[-1]}. Für eine Schätzung "
                       f"sagen Sie „Prognose für {jahr}“."))

    if "ohne prognose" in m or "keine prognose" in m:
        return Interpretation(action="set_prognose", prognose_jahre=[],
                              reply="Die Prognose ist ausgeblendet.")
    if any(w in m for w in ("prognose", "vorhersage", "schätz", "schaetz",
                            "hochrechnung", "forecast")):
        if jahre_im_text:
            return Interpretation(action="set_prognose",
                                  prognose_jahre=jahre_im_text,
                                  reply="Prognose berechnet – die Werte sind "
                                        "geschätzt, keine Messwerte.")
        return Interpretation(action="inform",
                              reply="Für welches Jahr soll ich die Prognose "
                                    "berechnen? Zum Beispiel „Prognose für 2026“.")

    # --- Mehrjahresvergleich in einer Nachricht ---
    if ("letzt" in m or "vergangen" in m) and "jahr" in m:
        kennzahl = "kosten" if "kosten" in m and "umsatz" not in m else "umsatz"
        return Interpretation(action="show_measure", measure=kennzahl,
                              group_by="jahr", chart_type="bar",
                              reply=f"Hier ist der {kennzahl.capitalize()} "
                                    f"im Jahresvergleich.")

    # --- Sachdimensionen als Achse ---
    if "kategorie" in m and ("nach" in m or "je" in m or "pro" in m or "gruppier" in m):
        return Interpretation(action="set_group_by", group_by="kategorie",
                              reply="Die Auswertung ist jetzt nach Produktkategorien gruppiert.")
    if "produkt" in m and ("nach" in m or "je" in m or "pro" in m or "gruppier" in m):
        return Interpretation(action="set_group_by", group_by="produkt",
                              reply="Die Auswertung ist jetzt nach Produkten gruppiert.")
    if "segment" in m and ("nach" in m or "je" in m or "pro" in m or "gruppier" in m):
        return Interpretation(action="set_group_by", group_by="segment",
                              reply="Die Auswertung ist jetzt nach Kundensegmenten gruppiert.")
    if "branche" in m and ("nach" in m or "je" in m or "pro" in m or "gruppier" in m):
        return Interpretation(action="set_group_by", group_by="branche",
                              reply="Die Auswertung ist jetzt nach Branchen gruppiert.")
    if "region" in m and ("nach" in m or "je" in m or "pro" in m or "gruppier" in m):
        return Interpretation(action="set_group_by", group_by="region",
                              reply="Die Auswertung ist jetzt nach Regionen gruppiert.")

    # --- Kategoriefilter ---
    for wort, kat in (("hardware", "hardware"), ("software", "software"),
                      ("service", "service")):
        if wort in m and ("nur" in m or "filter" in m or "beschr" in m):
            return Interpretation(action="set_kategorie_filter", kategorie=kat,
                                  reply=f"Die Auswertung ist auf {kat.capitalize()} eingeschränkt.")
    if "alle kategorien" in m or "ohne kategoriefilter" in m:
        return Interpretation(action="set_kategorie_filter", kategorie="",
                              reply="Der Kategoriefilter ist aufgehoben.")

    # --- Quartalsfilter (z.B. "nur Q2", "zweites Quartal") ---
    import re as _re
    q_treffer = _re.search(r"\bq([1-4])\b", m) or _re.search(r"([1-4])\.\s*quartal", m)
    if q_treffer and ("nur" in m or "vergleich" in m or "jeweils" in m or "q" in m):
        q = int(q_treffer.group(1))
        return Interpretation(action="set_quartal_filter", quartal=q,
                              reply=f"Die Auswertung ist auf Q{q} eingeschränkt.")
    for wort, q in (("erste", 1), ("zweite", 2), ("dritte", 3), ("vierte", 4)):
        if f"{wort}n quartal" in m or f"{wort} quartal" in m or f"{wort}s quartal" in m:
            return Interpretation(action="set_quartal_filter", quartal=q,
                                  reply=f"Die Auswertung ist auf Q{q} eingeschränkt.")
    if "alle quartale" in m or "ohne quartalsfilter" in m:
        return Interpretation(action="set_quartal_filter", quartal=0,
                              reply="Der Quartalsfilter ist aufgehoben.")

    # --- Werktagsfilter ---
    if "werktag" in m or ("ohne" in m and "wochenende" in m):
        return Interpretation(action="set_workday_filter", nur_werktage=True,
                              reply="Wochenenden sind jetzt ausgeblendet.")
    if "mit wochenende" in m or ("auch" in m and "wochenende" in m):
        return Interpretation(action="set_workday_filter", nur_werktage=False,
                              reply="Wochenenden werden wieder berücksichtigt.")

    if "säul" in m or "balken" in m:
        return Interpretation(action="set_chart_type", chart_type="bar",
                              reply="Erledigt — jetzt als Säulendiagramm.")
    if "linie" in m and ("verwende" in m or "als" in m or "zeige" in m) and "kosten" not in m and "gewinn" not in m:
        return Interpretation(action="set_chart_type", chart_type="line",
                              reply="Erledigt — jetzt als Liniendiagramm.")

    if "gewinn" in m and ("definier" in m or "neue kennzahl" in m or "=" in m):
        return Interpretation(action="define_kpi", kpi_name="gewinn",
                              kpi_expression="umsatz - kosten",
                              reply="Neue Kennzahl gespeichert: Gewinn = Umsatz − Kosten.")
    if "gewinn" in m and ("blende" in m or "zeige" in m or "grün" in m):
        return Interpretation(action="add_series", series_key="gewinn",
                              reply="Der Gewinn ist als grüne Linie eingeblendet.")
    if "kosten" in m and ("blende" in m or "zeige" in m or "rot" in m or "ein" in m):
        return Interpretation(action="add_series", series_key="kosten",
                              reply="Die Kosten sind als rote Linie ergänzt.")

    if ("umsatz" in m or "umsätze" in m or "umsaetze" in m or "gesamtumsatz" in m) \
            and ("monat" in m or "verlauf" in m or "stelle" in m or "dar" in m):
        return Interpretation(action="show_measure", measure="umsatz", chart_type="line",
                              reply="Hier ist der monatliche Umsatzverlauf.")

    # Noch kein Diagramm, aber eine Kennzahl genannt -> Auswertung starten.
    if not ctx.series:
        for wort, kennzahl in (("umsatz", "umsatz"), ("umsätze", "umsatz"),
                               ("umsaetze", "umsatz"), ("kosten", "kosten")):
            if wort in m:
                return Interpretation(action="show_measure", measure=kennzahl,
                                      chart_type="line",
                                      reply=f"Hier ist der Verlauf für "
                                            f"{kennzahl.capitalize()}.")

    # Nur ein Regionswort ohne Verb ("ausland")
    if m.strip() in ("inland", "ausland", "im inland", "im ausland"):
        region = "inland" if "inland" in m else "ausland"
        return Interpretation(action="set_filter", region=region,
                              reply=f"Ok, ich filtere auf das "
                                    f"{region.capitalize()}.")

    return Interpretation(action="none",
                          reply="Das habe ich nicht verstanden. Versuchen Sie z. B. "
                                "„Stelle den Umsatz nach Monaten dar.“")


# --- Hybride Interpretation ---------------------------------------------
def interpret(message: str, ctx: AnalysisContext, client=None,
              regeln_zuerst: bool = True) -> Interpretation:
    """Waehlt die Interpretationsstrategie.

    Hybrid (Standard): zuerst die deterministischen Regeln. Erkennen sie die
    Absicht eindeutig, wird deren Ergebnis genommen -- das ist reproduzierbar
    und immun gegen Fehlgriffe kleiner Modelle. Nur wenn die Regeln nichts
    erkennen, uebernimmt das Sprachmodell (freie Formulierungen, Tippfehler).

    Hintergrund: kleine lokale Modelle formulieren oft die richtige Antwort,
    waehlen aber die falsche Aktion (z.B. Text "Jahresvergleich", Aktion
    `show_measure`). Die Regeln verhindern genau das bei bekannten Befehlen.

    Mit `regeln_zuerst=False` laeuft ausschliesslich das Modell -- nuetzlich,
    um beide Varianten in der Evaluation zu vergleichen.
    """
    if client is None:
        return interpret_rule_based(message, ctx)

    if regeln_zuerst:
        regel = interpret_rule_based(message, ctx)
        if regel.action != "none":
            return regel

    return interpret_llm(message, ctx, client)


# --- Antworttexte absichern ----------------------------------------------
# Deterministische Bestaetigungen je Aktion. Sie dienen als Rueckfallebene,
# wenn ein (kleines) Modell eine abgeschnittene oder erfundene Antwort liefert.
_ACHSEN_TEXT = {
    "jahr": "Jahren", "quartal": "Quartalen", "monat": "Monaten",
    "kalenderwoche": "Kalenderwochen", "wochentag": "Wochentagen",
    "region": "Regionen", "kategorie": "Produktkategorien",
    "produkt": "Produkten", "segment": "Kundensegmenten", "branche": "Branchen",
}


def default_reply(interp: Interpretation, ctx: AnalysisContext) -> str:
    """Erzeugt eine korrekte Bestaetigung allein aus der Aktion."""
    a = interp.action
    if a == "set_filter":
        teile = []
        if interp.region:
            teile.append(sem.REGIONS.get(interp.region.lower(), interp.region))
        if interp.jahr:
            teile.append(str(interp.jahr))
        return f"Ok, Filter gesetzt: {' · '.join(teile)}." if teile \
            else "Ok, Filter aktualisiert."
    if a == "show_measure":
        label = sem.MEASURES[interp.measure].label \
            if interp.measure in sem.MEASURES else "Kennzahl"
        return f"Hier ist der Verlauf für {label}."
    if a == "set_chart_type":
        art = "Säulendiagramm" if interp.chart_type == "bar" else "Liniendiagramm"
        return f"Erledigt — jetzt als {art}."
    if a == "set_group_by":
        achse = _ACHSEN_TEXT.get(interp.group_by or "", "Monaten")
        return f"Die Auswertung ist jetzt nach {achse} gruppiert."
    if a == "set_prognose":
        return ("Prognose berechnet – die Werte sind geschätzt."
                if interp.prognose_jahre else "Die Prognose ist ausgeblendet.")
    if a == "set_kategorie_filter":
        return (f"Die Auswertung ist auf {interp.kategorie.capitalize()} eingeschränkt."
                if interp.kategorie else "Der Kategoriefilter ist aufgehoben.")
    if a == "set_quartal_filter":
        return (f"Die Auswertung ist auf Q{interp.quartal} eingeschränkt."
                if interp.quartal else "Der Quartalsfilter ist aufgehoben.")
    if a == "set_workday_filter":
        return ("Wochenenden sind jetzt ausgeblendet." if interp.nur_werktage
                else "Wochenenden werden wieder berücksichtigt.")
    if a == "add_series":
        return f"Die Reihe „{(interp.series_key or '').capitalize()}“ ist eingeblendet."
    if a == "define_kpi":
        name = (interp.kpi_name or "KPI").capitalize()
        return f"Neue Kennzahl gespeichert: {name} = {interp.kpi_expression}."
    if a == "list_data":
        return f"Verfügbare Regionen: {', '.join(available_regions(ctx.jahr))}."
    return "Die Werte sehen Sie im Diagramm."


def _looks_broken(text: str) -> bool:
    """Erkennt abgeschnittene oder halluzinierte Antworten kleiner Modelle."""
    t = (text or "").strip()
    if not t:
        return True
    # Abgeschnitten: kein Satzende
    if not t.endswith((".", "!", "?", "…")):
        return True
    if t.endswith("...") or t.endswith("…"):
        return True
    # Erfundene Datenwerte: Formulierungen, die eine Zahl ankuendigen
    lower = t.lower()
    if any(w in lower for w in ("beträgt", "betraegt", "liegt bei", "summe von")):
        return True
    return False


def sanitize(interp: Interpretation, ctx: AnalysisContext) -> Interpretation:
    """Ersetzt unbrauchbare Modellantworten durch eine deterministische."""
    if _looks_broken(interp.reply):
        interp.reply = default_reply(interp, ctx)
    return interp


# --- Ausfuehrung ---------------------------------------------------------
def apply(interp: Interpretation, ctx: AnalysisContext) -> str:
    """Fuehrt die Interpretation gegen die semantische Schicht aus."""
    a = interp.action
    try:
        if a == "set_filter":
            sem.set_filter(ctx, region=interp.region, jahr=interp.jahr)
        elif a == "show_measure":
            sem.show_measure(ctx, interp.measure or "umsatz",
                             chart_type=interp.chart_type or "line")
            # Optional gleich die Achse mitsetzen: "Umsatz der letzten 3 Jahre"
            # ist eine Absicht, soll aber nicht zwei Nachrichten erfordern.
            if interp.group_by:
                sem.set_group_by(ctx, interp.group_by)
        elif a == "set_chart_type":
            sem.set_chart_type(ctx, interp.chart_type or "line")
        elif a == "set_group_by":
            sem.set_group_by(ctx, interp.group_by or "monat")
        elif a == "goal_seek":
            basis, ziel = interp.basis_jahr, interp.ziel_jahr
            if not basis or not ziel:
                return ("Bitte Basis- und Zieljahr nennen, z. B. „Was hätte ich "
                        "tun müssen, um den Umsatz von 2025 schon 2023 zu "
                        "erreichen?“")
            sem.show_measure(ctx, interp.measure or "umsatz",
                             chart_type=interp.chart_type or "bar")
            sem.set_jahre_auswahl(ctx, sorted({basis, ziel}))
            sem.set_prognose(ctx, [])
            from . import goalseek
            return goalseek.describe(
                goalseek.analyse(ctx, basis, ziel_jahr=ziel,
                                 kennzahl=interp.measure or "umsatz"))
        elif a == "compare_periods":
            jahre = sorted((interp.vergleich_jahre or [])[:2])
            if len(jahre) < 2:
                return ("Bitte zwei Jahre nennen, z. B. "
                        "„Unterschied zwischen 2023 und 2024“.")
            sem.show_measure(ctx, interp.measure or "umsatz",
                             chart_type=interp.chart_type or "bar")
            sem.set_jahre_auswahl(ctx, jahre)
            sem.set_prognose(ctx, [])       # Prognose stoert den Vergleich
            from . import variance
            return variance.describe(
                variance.analyse(ctx, jahre[0], jahre[1],
                                 interp.measure or "umsatz"))
        elif a == "set_prognose":
            sem.set_prognose(ctx, interp.prognose_jahre)
            if not ctx.series:          # ohne Reihe waere nichts zu sehen
                sem.show_measure(ctx, "umsatz", chart_type="bar")
        elif a == "set_kategorie_filter":
            sem.set_kategorie_filter(ctx, interp.kategorie or None)
        elif a == "set_quartal_filter":
            sem.set_quartal_filter(ctx, interp.quartal or None)
        elif a == "set_workday_filter":
            sem.set_workdays_only(ctx, bool(interp.nur_werktage))
        elif a == "define_kpi":
            sem.define_kpi(ctx, interp.kpi_name or "kpi",
                           interp.kpi_expression or "umsatz - kosten")
        elif a == "add_series":
            sem.add_series(ctx, (interp.series_key or "").lower())
        # list_data / inform / none: keine Zustandsaenderung
    except ValueError as e:
        # Der Befehl wurde abgelehnt: die (ggf. erfundene) Modellantwort waere
        # irrefuehrend. Stattdessen die Fehlerursache verstaendlich melden.
        return str(e)

    # Behauptung gegen tatsaechlichen Zustand pruefen: kleine Modelle
    # formulieren gerne eine Aktion, die sie gar nicht ausgeloest haben.
    behauptung = interp.reply.lower()
    if "jahresvergleich" in behauptung and ctx.group_by != "jahr":
        return ("Ich habe die Auswertung nicht auf Jahre umgestellt. "
                "Sagen Sie bitte „Gruppiere nach Jahren“.")
    if "quartal" in behauptung and a not in ("set_group_by", "set_quartal_filter") \
            and ctx.group_by != "quartal" and not ctx.quartal:
        return ("Ich habe nichts an der Quartalseinstellung geändert. "
                "Sagen Sie z. B. „Gruppiere nach Quartalen“ oder „Nur Q2“.")

    # Solange keine Reihe gewaehlt ist, gibt es kein Diagramm. Ohne diesen
    # Hinweis behaupten kleine Modelle gelegentlich, es sei bereits eines da.
    if not ctx.series and a in ("set_filter", "set_group_by", "set_chart_type",
                                "set_workday_filter", "set_quartal_filter",
                                "set_kategorie_filter"):
        return (f"{interp.reply}\n\nEs wird noch kein Diagramm angezeigt. "
                "Sagen Sie z. B. „Zeige den Umsatz nach Monaten“.")
    return interp.reply
