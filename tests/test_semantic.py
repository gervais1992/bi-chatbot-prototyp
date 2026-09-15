"""Beispieltests fuer die semantische Schicht (Grundlage fuer Kapitel 6)."""
from bi_chatbot import interpreter as nlu
from bi_chatbot import semantic_layer as sem
from bi_chatbot.state import AnalysisContext


def test_set_filter():
    ctx = AnalysisContext()
    sem.set_filter(ctx, region="inland")
    assert ctx.region == "Inland"


def test_show_measure_replaces_series():
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz", chart_type="line")
    assert len(ctx.series) == 1
    assert ctx.series[0].key == "umsatz"
    assert ctx.chart_type == "line"


def test_chart_type_change_keeps_series():
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz")
    sem.set_chart_type(ctx, "bar")
    assert ctx.chart_type == "bar"
    assert len(ctx.series) == 1  # reine Visualisierungsaenderung


def test_define_and_compute_kpi():
    ctx = AnalysisContext()
    sem.define_kpi(ctx, "gewinn", "umsatz - kosten")
    assert ctx.kpis["gewinn"] == ("umsatz", "-", "kosten")
    base = {"umsatz": [100.0, 200.0], "kosten": [60.0, 90.0]}
    assert sem.compute_series_values("gewinn", base, ctx) == [40.0, 110.0]


def test_full_example_dialog():
    """Spielt den Beispieldialog regelbasiert durch."""
    ctx = AnalysisContext()
    steps = [
        "Welche Verkaufszahlen gibt es für das Jahr 2025?",
        "Nimm bitte die Umsätze im Inland.",
        "Stelle den Gesamtumsatz nach Monaten dar.",
        "Verwende bitte Säulen statt Linien.",
        "Blende die Kosten als rote Linie ein.",
        "Definiere eine neue Kennzahl „Gewinn“ = Umsatz − Kosten.",
        "Blende eine grüne Linie für den Gewinn ein.",
    ]
    for s in steps:
        interp = nlu.interpret_rule_based(s, ctx)
        nlu.apply(interp, ctx)

    assert ctx.region == "Inland"
    assert ctx.chart_type == "bar"
    assert "gewinn" in ctx.kpis
    keys = {s.key for s in ctx.series}
    assert {"umsatz", "kosten", "gewinn"} <= keys


# --- Zeitachse und Werktagsfilter ---------------------------------------
def test_set_group_by_valid():
    ctx = AnalysisContext()
    sem.set_group_by(ctx, "quartal")
    assert ctx.group_by == "quartal"


def test_group_by_niemals_freitext_in_sql():
    """Sicherheitseigenschaft: der Zustand enthaelt IMMER nur Vokabular.

    Entstellte oder boesartige Eingaben werden entweder auf einen gueltigen
    Schluessel abgebildet oder abgelehnt -- nie durchgereicht. Damit kann kein
    Freitext in die SQL-Erzeugung gelangen.
    """
    import pytest
    ctx = AnalysisContext()

    # Enthaelt ein bekanntes Wort -> wird sicher darauf abgebildet
    sem.set_group_by(ctx, "monat; DROP TABLE fakt_verkauf")
    assert ctx.group_by in sem.GROUPINGS

    # Voellig unbekannt -> Ablehnung, Zustand unveraendert
    vorher = ctx.group_by
    with pytest.raises(ValueError):
        sem.set_group_by(ctx, "'; DELETE FROM dim_zeit; --")
    assert ctx.group_by == vorher
    assert ctx.group_by in sem.GROUPINGS


def test_resolve_entstellte_eingaben():
    """Tippfehler kleiner Modelle werden dem Vokabular zugeordnet."""
    kandidaten = ["umsatz", "kosten"]
    assert sem.resolve("umstoericht", kandidaten) == "umsatz"   # realer Fall
    assert sem.resolve("Umsätze", kandidaten) == "umsatz"
    assert sem.resolve("kostn", kandidaten) == "kosten"
    assert sem.resolve("marktanteil", kandidaten) is None


def test_unbekannte_kennzahl_meldet_verfuegbare():
    """Die Fehlermeldung nennt die tatsaechlich verfuegbaren Kennzahlen."""
    from bi_chatbot.schema import Interpretation
    ctx = AnalysisContext()
    interp = Interpretation(action="show_measure", measure="marktanteil",
                            reply="Erledigt.")
    antwort = nlu.apply(interp, ctx)
    assert "Umsatz" in antwort and "Kosten" in antwort
    assert ctx.series == []  # nichts veraendert


def test_workday_filter():
    ctx = AnalysisContext()
    assert ctx.nur_werktage is False
    sem.set_workdays_only(ctx, True)
    assert ctx.nur_werktage is True


def test_group_by_changes_axis_length():
    """Der Achsenwechsel wirkt sich auf die geladenen Daten aus."""
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.set_filter(ctx, region="inland")
    sem.show_measure(ctx, "umsatz")

    labels_monat, _ = load_base_measures(ctx)
    assert len(labels_monat) == 12

    sem.set_group_by(ctx, "quartal")
    labels_quartal, _ = load_base_measures(ctx)
    assert labels_quartal == ["Q1", "Q2", "Q3", "Q4"]

    sem.set_group_by(ctx, "jahr")
    labels_jahr, _ = load_base_measures(ctx)
    # Jahresfilter greift hier nicht -> alle Geschaeftsjahre erscheinen
    assert len(labels_jahr) >= 3
    assert str(ctx.jahr) in labels_jahr


def test_workday_filter_reduces_values():
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.set_filter(ctx, region="inland")
    sem.show_measure(ctx, "umsatz")
    _, mit = load_base_measures(ctx)
    sem.set_workdays_only(ctx, True)
    _, ohne = load_base_measures(ctx)
    assert sum(ohne["umsatz"]) < sum(mit["umsatz"])


def test_dialog_mit_zeitachsen():
    """Erweiterter Beispieldialog inkl. Quartals- und Werktagsbefehl."""
    ctx = AnalysisContext()
    for s in ["Nimm bitte die Umsätze im Inland.",
              "Stelle den Gesamtumsatz nach Monaten dar.",
              "Gruppiere bitte nach Quartalen.",
              "Zeige nur Werktage."]:
        nlu.apply(nlu.interpret_rule_based(s, ctx), ctx)
    assert ctx.group_by == "quartal"
    assert ctx.nur_werktage is True


# --- Absicherung der Antworttexte (kleine lokale Modelle) ----------------
def test_sanitize_ersetzt_abgeschnittene_antwort():
    from bi_chatbot.schema import Interpretation
    ctx = AnalysisContext()
    interp = Interpretation(action="set_group_by", group_by="quartal",
                            reply="Die Umsatz für die Quartal 2 beträgt")
    nlu.sanitize(interp, ctx)
    assert interp.reply.endswith(".")
    assert "beträgt" not in interp.reply
    assert "Quartalen" in interp.reply


def test_sanitize_ersetzt_erfundene_zahlen():
    from bi_chatbot.schema import Interpretation
    ctx = AnalysisContext()
    interp = Interpretation(action="set_chart_type", chart_type="bar",
                            reply="Der Umsatz beträgt 2.684 Tsd EUR.")
    nlu.sanitize(interp, ctx)
    assert "2.684" not in interp.reply


def test_sanitize_behaelt_korrekte_antwort():
    from bi_chatbot.schema import Interpretation
    ctx = AnalysisContext()
    original = "Wochenenden sind jetzt ausgeblendet."
    interp = Interpretation(action="set_workday_filter", nur_werktage=True,
                            reply=original)
    nlu.sanitize(interp, ctx)
    assert interp.reply == original


def test_default_reply_fuer_alle_aktionen():
    """Jede Aktion hat eine brauchbare Rueckfallantwort."""
    from bi_chatbot.schema import Interpretation
    ctx = AnalysisContext()
    aktionen = [
        Interpretation(action="set_filter", region="inland", reply=""),
        Interpretation(action="show_measure", measure="umsatz", reply=""),
        Interpretation(action="set_chart_type", chart_type="line", reply=""),
        Interpretation(action="set_group_by", group_by="jahr", reply=""),
        Interpretation(action="set_workday_filter", nur_werktage=False, reply=""),
        Interpretation(action="add_series", series_key="kosten", reply=""),
        Interpretation(action="define_kpi", kpi_name="gewinn",
                       kpi_expression="umsatz - kosten", reply=""),
        Interpretation(action="none", reply=""),
    ]
    for interp in aktionen:
        text = nlu.default_reply(interp, ctx)
        assert text and text.endswith(".")


# --- Quartalsfilter ------------------------------------------------------
def test_quartalsfilter_setzen_und_aufheben():
    ctx = AnalysisContext()
    sem.set_quartal_filter(ctx, 2)
    assert ctx.quartal == 2
    sem.set_quartal_filter(ctx, None)
    assert ctx.quartal is None


def test_quartalsfilter_lehnt_ungueltige_werte_ab():
    import pytest
    ctx = AnalysisContext()
    for wert in (0, 5, -1, "zwei"):
        with pytest.raises(ValueError):
            sem.set_quartal_filter(ctx, wert)
    assert ctx.quartal is None


def test_q2_vergleich_ueber_alle_jahre():
    """Kernszenario: dasselbe Quartal ueber mehrere Geschaeftsjahre."""
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    for s in ["Zeige den Umsatz nach Monaten.",
              "Nimm bitte die Umsätze im Inland.",
              "Nur Q2 bitte.",
              "Mach einen Jahresvergleich."]:
        nlu.apply(nlu.interpret_rule_based(s, ctx), ctx)

    assert ctx.quartal == 2
    assert ctx.group_by == "jahr"
    labels, base = load_base_measures(ctx)
    assert len(labels) >= 3                       # ein Punkt je Jahr
    assert all(v > 0 for v in base["umsatz"])


def test_quartalsfilter_reduziert_werte():
    """Ein Quartal muss weniger Umsatz enthalten als das ganze Jahr."""
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.set_filter(ctx, region="inland")
    sem.show_measure(ctx, "umsatz")
    sem.set_group_by(ctx, "jahr")
    _, ganzes_jahr = load_base_measures(ctx)
    sem.set_quartal_filter(ctx, 2)
    _, nur_q2 = load_base_measures(ctx)
    assert sum(nur_q2["umsatz"]) < sum(ganzes_jahr["umsatz"])


# --- Sachdimensionen und Kategoriefilter ---------------------------------
def test_gruppierung_nach_sachdimensionen():
    """Produkt, Kategorie, Segment und Branche sind als Achse nutzbar."""
    from bi_chatbot.db import load_base_measures
    for achse, mindestens in [("kategorie", 3), ("produkt", 8),
                              ("segment", 3), ("region", 2)]:
        ctx = AnalysisContext()
        sem.show_measure(ctx, "umsatz")
        sem.set_group_by(ctx, achse)
        labels, base = load_base_measures(ctx)
        assert len(labels) >= mindestens, achse
        assert all(v > 0 for v in base["umsatz"]), achse


def test_kategoriefilter():
    ctx = AnalysisContext()
    sem.set_kategorie_filter(ctx, "software")
    assert ctx.kategorie == "Software"
    sem.set_kategorie_filter(ctx, None)
    assert ctx.kategorie is None


def test_kategoriefilter_lehnt_unbekanntes_ab():
    import pytest
    ctx = AnalysisContext()
    with pytest.raises(ValueError):
        sem.set_kategorie_filter(ctx, "zubehoer")
    assert ctx.kategorie is None


def test_kategoriefilter_reduziert_umsatz():
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz")
    sem.set_group_by(ctx, "jahr")
    _, alle = load_base_measures(ctx)
    sem.set_kategorie_filter(ctx, "software")
    _, nur_sw = load_base_measures(ctx)
    assert sum(nur_sw["umsatz"]) < sum(alle["umsatz"])


def test_dialog_kategorie_und_segment():
    ctx = AnalysisContext()
    for s in ["Zeige den Umsatz nach Monaten.",
              "Gruppiere nach Produktkategorie.",
              "Nur Software bitte."]:
        nlu.apply(nlu.interpret_rule_based(s, ctx), ctx)
    assert ctx.group_by == "kategorie"
    assert ctx.kategorie == "Software"


def test_verlauf_momentaufnahme_ist_unabhaengig():
    """Eine Kopie des Kontexts darf sich nicht mitveraendern."""
    import copy
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz")
    schnappschuss = copy.deepcopy(ctx)
    sem.set_group_by(ctx, "kategorie")
    sem.set_kategorie_filter(ctx, "hardware")
    assert schnappschuss.group_by == "monat"
    assert schnappschuss.kategorie is None
    assert ctx.group_by == "kategorie"


# --- Textuelle Zusammenfassung ------------------------------------------
def test_narrative_nennt_echte_zahlen():
    """Der Text stammt aus den geladenen Daten, nicht vom Modell."""
    from bi_chatbot import narrative
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz")
    sem.set_group_by(ctx, "jahr")
    labels, base = load_base_measures(ctx)
    text = narrative.describe(ctx, labels, base)
    assert "Umsatz" in text
    for lab in labels:
        assert lab in text            # jedes Jahr wird genannt
    assert "Mio. €" in text or "Tsd. €" in text


def test_narrative_ohne_prozente_bei_sachdimensionen():
    """Zwischen Kategorien waere eine Veraenderungsrate irrefuehrend."""
    from bi_chatbot import narrative
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz")
    sem.set_group_by(ctx, "kategorie")
    labels, base = load_base_measures(ctx)
    text = narrative.describe(ctx, labels, base)
    assert "%" not in text
    assert "Hardware" in text


def test_narrative_leer_ohne_diagramm():
    from bi_chatbot import narrative
    ctx = AnalysisContext()
    assert narrative.describe(ctx, [], {}) == ""


def test_mehrjahresabfrage_in_einer_nachricht():
    """„Umsatz der letzten 3 Jahre“ setzt Kennzahl und Achse zugleich."""
    ctx = AnalysisContext()
    interp = nlu.interpret_rule_based("Umsatz der letzten 3 Jahre", ctx)
    nlu.apply(interp, ctx)
    assert ctx.group_by == "jahr"
    assert [s.key for s in ctx.series] == ["umsatz"]


# --- Prognose ------------------------------------------------------------
def test_jahr_ohne_daten_wird_gemeldet():
    """Ein Jahr ausserhalb des Bestands darf nicht stillschweigend ignoriert werden."""
    ctx = AnalysisContext()
    antwort = nlu.apply(nlu.interpret_rule_based("Zeige den Umsatz von 2016.", ctx), ctx)
    assert "2016" in antwort and "keine Daten" in antwort
    assert ctx.series == []


def test_set_filter_lehnt_unbekanntes_jahr_ab():
    import pytest
    ctx = AnalysisContext()
    with pytest.raises(ValueError):
        sem.set_filter(ctx, jahr=1999)


def test_prognose_ergaenzt_zukunftsjahre():
    from bi_chatbot import forecast
    labels = ["2023", "2024", "2025"]
    base = {"umsatz": [10.0, 12.0, 14.0]}
    neu, werte, prog = forecast.predict(labels, base, [2026])
    assert neu == ["2023", "2024", "2025", "2026"]
    assert prog == {"2026"}
    assert werte["umsatz"][3] > werte["umsatz"][2]   # Trend fortgeschrieben
    assert werte["umsatz"][:3] == [10.0, 12.0, 14.0]  # Messwerte unveraendert


def test_prognose_wird_im_text_gekennzeichnet():
    from bi_chatbot import forecast, narrative
    from bi_chatbot.db import load_base_measures
    ctx = AnalysisContext()
    sem.show_measure(ctx, "umsatz")
    sem.set_prognose(ctx, [2026])
    labels, base = load_base_measures(ctx)
    labels, base, prog = forecast.predict(labels, base, ctx.prognose_jahre)
    text = narrative.describe(ctx, labels, base, prognose=prog)
    assert "(Prognose)" in text


def test_rueckrechnung_wird_als_unbelastbar_gekennzeichnet():
    from bi_chatbot import forecast
    hinweis = forecast.guete_hinweis(["2023", "2024", "2025"],
                                     [10e6, 12e6, 14e6], [2016])
    assert "nicht belastbar" in hinweis


def test_prognose_aufheben():
    ctx = AnalysisContext()
    sem.set_prognose(ctx, [2026])
    assert ctx.prognose_jahre == [2026]
    sem.set_prognose(ctx, [])
    assert ctx.prognose_jahre == []
