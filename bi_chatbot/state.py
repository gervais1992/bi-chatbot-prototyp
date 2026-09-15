"""Dialog- und Analysezustand.

Der `AnalysisContext` ist das Herzstueck des "lernfaehigen" Verhaltens:
er speichert, worueber gerade gesprochen wird (Filter, Diagrammtyp,
aktive Datenreihen, zur Laufzeit definierte Kennzahlen). Der Dialog-Manager
liest und aktualisiert diesen Zustand von Turn zu Turn.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Series:
    """Eine im Diagramm angezeigte Datenreihe."""
    key: str            # 'umsatz', 'kosten', 'gewinn', ...
    label: str          # Anzeigename
    color: str          # Hex-Farbe
    kind: str           # 'measure' oder 'kpi'


@dataclass
class AnalysisContext:
    """Vollstaendiger Zustand einer laufenden Auswertung."""
    jahr: int = 2025
    region: str | None = None                 # 'Inland' | 'Ausland' | None
    quartal: int | None = None                 # 1..4, None = alle Quartale
    kategorie: str | None = None               # Hardware | Software | Service
    prognose_jahre: list[int] = field(default_factory=list)  # extrapolierte Jahre
    group_by: str = "monat"                    # Zeitachse, siehe GROUPINGS
    nur_werktage: bool = False                 # Wochenenden ausblenden
    chart_type: str = "line"                   # 'line' | 'bar'
    series: list[Series] = field(default_factory=list)
    kpis: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    # kpis: name -> (linker_operand, operator, rechter_operand), z.B. ('umsatz','-','kosten')

    # --- Hilfsmethoden ---------------------------------------------------
    def has_series(self, key: str) -> bool:
        return any(s.key == key for s in self.series)

    def add_series(self, series: Series) -> None:
        if not self.has_series(series.key):
            self.series.append(series)

    def base_measures(self) -> list[str]:
        """Alle Basiskennzahlen, die aus der DB geladen werden muessen."""
        needed: set[str] = set()
        for s in self.series:
            if s.kind == "measure":
                needed.add(s.key)
            else:  # KPI: Operanden aufloesen
                left, _op, right = self.kpis[s.key]
                needed.update([left, right])
        # Immer Basis-Kennzahlen bereithalten, damit KPIs definierbar sind
        needed.update({"umsatz", "kosten"})
        return sorted(needed)

    def summary(self) -> str:
        # Beim Gruppieren nach Jahr wirkt der Jahresfilter nicht (Jahresvergleich).
        if self.group_by == "jahr":
            f = self.region or "alle Regionen"
        else:
            f = f"{self.region} · {self.jahr}" if self.region else f"— · {self.jahr}"
        if self.quartal:
            f += f" · nur Q{self.quartal}"
        if self.kategorie:
            f += f" · {self.kategorie}"
        if self.prognose_jahre:
            f += " · inkl. Prognose " + ", ".join(str(j) for j in self.prognose_jahre)
        if self.nur_werktage:
            f += " · nur Werktage"
        t = {"line": "Linie", "bar": "Säulen"}.get(self.chart_type, self.chart_type)
        achse = {"jahr": "Jahr", "quartal": "Quartal", "monat": "Monat",
                 "kalenderwoche": "KW", "wochentag": "Wochentag",
                 "region": "Region", "kategorie": "Kategorie",
                 "produkt": "Produkt", "segment": "Segment",
                 "branche": "Branche"}.get(self.group_by, self.group_by)
        reihen = ", ".join(s.label for s in self.series) or "keine"
        return (f"Filter: {f} | Achse: {achse} | Diagramm: {t} | "
                f"Reihen: {reihen}")
