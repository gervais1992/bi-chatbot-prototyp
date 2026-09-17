"""Semantische Schicht (Kennzahlen-Layer).

Definiert die fachlichen Kennzahlen und Dimensionen und uebersetzt die vom
NLU-Modul erkannten Kommandos in Aenderungen am `AnalysisContext`. Die
LLM-Komponente erzeugt hier NIE direkt SQL, sondern nur strukturierte
Kommandos gegen dieses kontrollierte Vokabular -> sicher und testbar.
"""
from __future__ import annotations
from dataclasses import dataclass

from .state import AnalysisContext, Series


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    column: str


# --- Fachliches Vokabular ------------------------------------------------
MEASURES: dict[str, Measure] = {
    "umsatz": Measure("umsatz", "Umsatz", "umsatz"),
    "kosten": Measure("kosten", "Kosten", "kosten"),
}

REGIONS = {"inland": "Inland", "ausland": "Ausland"}
KATEGORIEN = {"hardware": "Hardware", "software": "Software",
              "service": "Service"}


@dataclass(frozen=True)
class Grouping:
    """Eine Achse der Auswertung (Zeit oder Sachdimension)."""
    key: str
    label: str            # Anzeigename fuer die Achse
    column: str           # Spalte mit dem Anzeigewert
    order_column: str     # Spalte, nach der sortiert wird
    alias: str = "z"      # Tabellenalias (z=Zeit, r=Region, p=Produkt, ...)
    joins: tuple[str, ...] = ()   # zusaetzlich noetige Verbunde


# Kontrolliertes Vokabular der Zeitachsen. Das LLM darf NUR diese Schluessel
# nennen; die SQL-Ausdruecke stammen ausschliesslich aus dieser Tabelle und
# nie aus der Nutzereingabe -> keine SQL-Injection moeglich.
GROUPINGS: dict[str, Grouping] = {
    "jahr": Grouping("jahr", "Jahr", "jahr", "jahr"),
    "quartal": Grouping("quartal", "Quartal", "quartal_label", "quartal"),
    "monat": Grouping("monat", "Monat", "monat", "monat_nr"),
    "kalenderwoche": Grouping("kalenderwoche", "Kalenderwoche",
                              "kalenderwoche", "kalenderwoche"),
    "wochentag": Grouping("wochentag", "Wochentag", "wochentag", "wochentag_nr"),
    # --- Sachdimensionen (keine Zeitachsen) ---
    "region": Grouping("region", "Region", "region", "region", alias="r"),
    "kategorie": Grouping("kategorie", "Produktkategorie", "kategorie",
                          "kategorie", alias="k", joins=("produkt", "kategorie")),
    "produkt": Grouping("produkt", "Produkt", "produkt", "produkt",
                        alias="p", joins=("produkt",)),
    "segment": Grouping("segment", "Kundensegment", "segment", "segment",
                        alias="ku", joins=("kunde",)),
    "branche": Grouping("branche", "Branche", "branche", "branche",
                        alias="ku", joins=("kunde",)),
}

# Achsen, die keine Zeitachsen sind (der Jahresfilter greift dort weiterhin)
SACHDIMENSIONEN = {"region", "kategorie", "produkt", "segment", "branche"}

# Standardfarben pro Reihe (an das UI/Prototyp-Design angelehnt)
COLORS = {
    "umsatz": "#2f6fdd",
    "kosten": "#d64545",
    "gewinn": "#3f8f2e",
}
_FALLBACK_COLORS = ["#8a5cf6", "#e08a1e", "#0f9e75", "#c0397b"]


def _color_for(key: str, used: list[str]) -> str:
    if key in COLORS:
        return COLORS[key]
    for c in _FALLBACK_COLORS:
        if c not in used:
            return c
    return "#888888"


# --- Tolerante Aufloesung gegen das Vokabular ----------------------------
def resolve(value: str | None, candidates: list[str]) -> str | None:
    """Ordnet eine (moeglicherweise entstellte) Eingabe dem Vokabular zu.

    Kleine lokale Modelle verschreiben sich haeufig ("umstoericht" statt
    "umsatz") oder nutzen Beugungsformen ("Umsätze"). Diese Funktion faengt
    das ab, ohne das kontrollierte Vokabular aufzuweichen: es wird immer ein
    gueltiger Schluessel zurueckgegeben oder None.
    """
    import difflib

    if not value:
        return None
    v = value.strip().lower()
    if not v or not candidates:
        return None

    # 1. Exakter Treffer
    if v in candidates:
        return v
    # 2. Teilzeichenkette in beide Richtungen ("umsaetze" enthaelt "umsa")
    for c in candidates:
        if v in c or c in v:
            return c
    # 3. Aehnlichkeit (Tippfehler, Umlautschreibweisen)
    treffer = difflib.get_close_matches(v, candidates, n=1, cutoff=0.6)
    if treffer:
        return treffer[0]
    # 4. Gemeinsamer Wortanfang ab drei Zeichen ("ums..." -> "umsatz")
    for c in candidates:
        if len(v) >= 3 and len(c) >= 3 and v[:3] == c[:3]:
            return c
    # 5. Letzte, groszuegigere Aehnlichkeitspruefung
    treffer = difflib.get_close_matches(v, candidates, n=1, cutoff=0.45)
    return treffer[0] if treffer else None


def _bekannte_reihen(ctx: AnalysisContext) -> list[str]:
    return list(MEASURES) + list(ctx.kpis)


def label_for(key: str, ctx: AnalysisContext) -> str:
    if key in MEASURES:
        return MEASURES[key].label
    return key.capitalize()  # KPI-Name


def make_series(key: str, ctx: AnalysisContext) -> Series:
    kind = "measure" if key in MEASURES else "kpi"
    used = [s.color for s in ctx.series]
    return Series(key=key, label=label_for(key, ctx),
                  color=_color_for(key, used), kind=kind)


# --- Kommandos anwenden --------------------------------------------------
def set_filter(ctx: AnalysisContext, region: str | None = None,
               jahr: int | None = None) -> None:
    if region:
        key = resolve(region, list(REGIONS))
        if key is None:
            raise ValueError(
                f"„{region}“ kenne ich nicht. Verfügbar: "
                f"{', '.join(REGIONS.values())}."
            )
        ctx.region = REGIONS[key]
    if jahr:
        from .db import available_years
        vorhanden = available_years()
        if vorhanden and jahr not in vorhanden:
            raise ValueError(
                f"Für {jahr} liegen keine Daten vor. Verfügbar: "
                f"{vorhanden[0]}–{vorhanden[-1]}. Für eine Schätzung sagen Sie "
                f"z. B. „Prognose für {jahr}“."
            )
        ctx.jahr = jahr


def show_measure(ctx: AnalysisContext, measure: str,
                 chart_type: str = "line") -> None:
    """Startet eine neue Auswertung mit genau einer Reihe."""
    key = resolve(measure, list(MEASURES))
    if key is None:
        raise ValueError(
            f"Die Kennzahl „{measure}“ kenne ich nicht. Verfügbar: "
            f"{', '.join(m.label for m in MEASURES.values())}."
        )
    ctx.chart_type = chart_type
    ctx.series = [make_series(key, ctx)]


def set_chart_type(ctx: AnalysisContext, chart_type: str) -> None:
    if chart_type not in ("line", "bar"):
        raise ValueError(f"Unbekannter Diagrammtyp: {chart_type}")
    ctx.chart_type = chart_type  # reine Visualisierungsaenderung, keine Abfrage


def set_group_by(ctx: AnalysisContext, group_by: str) -> None:
    """Wechselt das Aggregationsniveau der Zeitachse (Monat, Quartal, ...)."""
    key = resolve(group_by, list(GROUPINGS))
    if key is None:
        raise ValueError(
            f"Die Zeitachse „{group_by}“ kenne ich nicht. Möglich: "
            f"{', '.join(g.label for g in GROUPINGS.values())}."
        )
    ctx.group_by = key


def set_jahre_auswahl(ctx: AnalysisContext, jahre: list[int] | None) -> None:
    """Beschraenkt die Jahresachse auf bestimmte Jahre (leer = alle)."""
    if not jahre:
        ctx.jahre_auswahl = []
        return
    from .db import available_years
    vorhanden = available_years()
    fehlend = [j for j in jahre if j not in vorhanden]
    if fehlend:
        raise ValueError(
            f"Für {fehlend[0]} liegen keine Daten vor. Verfügbar: "
            f"{vorhanden[0]}–{vorhanden[-1]}."
        )
    ctx.jahre_auswahl = sorted(set(jahre))
    ctx.group_by = "jahr"


def set_prognose(ctx: AnalysisContext, jahre: list[int] | None) -> None:
    """Aktiviert die Trendprognose fuer die genannten Jahre.

    Die Prognose ist nur auf der Jahresachse sinnvoll; die Achse wird daher
    mitgesetzt. Eine leere Liste hebt die Prognose auf.
    """
    if not jahre:
        ctx.prognose_jahre = []
        return
    gueltig = [int(j) for j in jahre if 1900 < int(j) < 2200]
    if not gueltig:
        raise ValueError("Bitte ein Jahr zwischen 1900 und 2200 angeben.")
    ctx.prognose_jahre = sorted(set(gueltig))
    ctx.group_by = "jahr"


def set_kategorie_filter(ctx: AnalysisContext, kategorie: str | None) -> None:
    """Beschraenkt die Auswertung auf eine Produktkategorie oder hebt das auf."""
    if not kategorie:
        ctx.kategorie = None
        return
    key = resolve(kategorie, list(KATEGORIEN))
    if key is None:
        raise ValueError(
            f"Die Kategorie „{kategorie}“ kenne ich nicht. Verfügbar: "
            f"{', '.join(KATEGORIEN.values())}."
        )
    ctx.kategorie = KATEGORIEN[key]


def set_quartal_filter(ctx: AnalysisContext, quartal: int | None) -> None:
    """Beschraenkt die Auswertung auf ein Quartal (1..4) oder hebt das auf.

    In Verbindung mit group_by="jahr" erlaubt das den Vergleich desselben
    Quartals ueber mehrere Geschaeftsjahre hinweg.
    """
    if quartal is None:
        ctx.quartal = None
        return
    try:
        q = int(quartal)
    except (TypeError, ValueError):
        raise ValueError(f"„{quartal}“ ist kein gültiges Quartal (1–4).") from None
    if q not in (1, 2, 3, 4):
        raise ValueError(f"Quartal {q} gibt es nicht. Möglich: 1, 2, 3 oder 4.")
    ctx.quartal = q


def set_workdays_only(ctx: AnalysisContext, nur_werktage: bool) -> None:
    """Blendet Wochenenden aus bzw. wieder ein."""
    ctx.nur_werktage = bool(nur_werktage)


def add_series(ctx: AnalysisContext, key: str) -> None:
    aufgeloest = resolve(key, _bekannte_reihen(ctx))
    if aufgeloest is None:
        raise ValueError(
            f"Die Reihe „{key}“ kenne ich nicht. Verfügbar: "
            f"{', '.join(_bekannte_reihen(ctx))}."
        )
    ctx.add_series(make_series(aufgeloest, ctx))


def define_kpi(ctx: AnalysisContext, name: str, expression: str) -> None:
    """Registriert eine abgeleitete Kennzahl, z.B. 'gewinn' = 'umsatz - kosten'."""
    key = name.strip().lower()
    left, op, right = _parse_expression(expression)
    aufgeloest = []
    for operand in (left, right):
        treffer = resolve(operand, _bekannte_reihen(ctx))
        if treffer is None:
            raise ValueError(
                f"„{operand}“ ist keine bekannte Kennzahl. Verfügbar: "
                f"{', '.join(_bekannte_reihen(ctx))}."
            )
        aufgeloest.append(treffer)
    ctx.kpis[key] = (aufgeloest[0], op, aufgeloest[1])
    if key not in COLORS and key == "gewinn":
        COLORS[key] = "#3f8f2e"


def _parse_expression(expr: str) -> tuple[str, str, str]:
    """Sehr einfacher Parser fuer 'a - b' oder 'a + b'."""
    for op in ("-", "+"):
        if op in expr:
            left, right = expr.split(op, 1)
            return left.strip().lower(), op, right.strip().lower()
    raise ValueError(f"Ausdruck nicht interpretierbar (nur + / - unterstuetzt): {expr}")


def compute_series_values(key: str, base: dict[str, list[float]],
                          ctx: AnalysisContext) -> list[float]:
    """Berechnet die Werte einer Reihe aus den geladenen Basiskennzahlen."""
    if key in MEASURES:
        return base[key]
    left, op, right = ctx.kpis[key]
    lv = compute_series_values(left, base, ctx)
    rv = compute_series_values(right, base, ctx)
    if op == "-":
        return [a - b for a, b in zip(lv, rv)]
    return [a + b for a, b in zip(lv, rv)]


def _jahre_text() -> str:
    """Jahre mit Datenbestand -- damit das LLM keine erfindet."""
    try:
        from .db import available_years
        j = available_years()
        return f"{j[0]}-{j[-1]}" if j else "unbekannt"
    except Exception:  # noqa: BLE001
        return "unbekannt"


def describe_for_prompt(ctx: AnalysisContext) -> str:
    """Kontextbeschreibung fuer den System-Prompt (RAG-artige Erdung)."""
    kpis = ", ".join(f"{k} = {l} {o} {r}" for k, (l, o, r) in ctx.kpis.items()) or "keine"
    diagramm = ("JA" if ctx.series
                else "NEIN -- es wird noch KEIN Diagramm angezeigt")
    return (
        f"Verfuegbare Kennzahlen: {', '.join(MEASURES)}\n"
        f"Verfuegbare Regionen: {', '.join(REGIONS.values())}\n"
        f"Moegliche Achsen (group_by): {', '.join(GROUPINGS)}\n"
        f"Verfuegbare Kategorien: {', '.join(KATEGORIEN.values())}\n"
        f"Verfuegbare Jahre: {_jahre_text()}\n"
        f"Kategoriefilter: {ctx.kategorie or 'keiner'}\n"
        f"Quartalsfilter: {('Q' + str(ctx.quartal)) if ctx.quartal else 'keiner'}\n"
        f"Definierte KPIs: {kpis}\n"
        f"Diagramm bereits vorhanden: {diagramm}\n"
        f"Aktueller Zustand: {ctx.summary()}"
    )
