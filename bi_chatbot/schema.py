"""Strukturiertes Ausgabeschema des NLU-Moduls.

Das LLM gibt NICHT SQL oder freien Text mit Nebenwirkungen zurueck, sondern
genau ein `Interpretation`-Objekt: eine erkannte Aktion samt Parametern und
eine natuerlichsprachige Antwort. Das haelt das System sicher und testbar.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Action = Literal[
    "list_data",         # verfuegbare Dimensionen/Regionen nennen
    "set_filter",        # Region/Jahr setzen
    "show_measure",      # neue Auswertung mit einer Kennzahl starten
    "set_chart_type",    # Linie <-> Saeulen
    "set_group_by",      # Zeitachse wechseln (Monat, Quartal, Jahr, ...)
    "set_workday_filter",  # nur Werktage / auch Wochenenden
    "set_quartal_filter",  # auf ein Quartal einschraenken (Q1..Q4)
    "set_kategorie_filter",  # auf eine Produktkategorie einschraenken
    "add_series",        # zusaetzliche Reihe (Kennzahl oder KPI) einblenden
    "define_kpi",        # neue Kennzahl zur Laufzeit definieren
    "none",              # Smalltalk / nichts zu tun
]


class Interpretation(BaseModel):
    action: Action = Field(description="Die erkannte Nutzerabsicht.")
    measure: Optional[str] = Field(
        None, description="Kennzahl-Schluessel, z.B. 'umsatz' (fuer show_measure)."
    )
    region: Optional[str] = Field(
        None, description="'inland' oder 'ausland' (fuer set_filter)."
    )
    jahr: Optional[int] = Field(None, description="Jahr, z.B. 2025 (fuer set_filter).")
    chart_type: Optional[Literal["line", "bar"]] = Field(
        None, description="Diagrammtyp (fuer set_chart_type oder show_measure)."
    )
    group_by: Optional[
        Literal["jahr", "quartal", "monat", "kalenderwoche", "wochentag",
            "region", "kategorie", "produkt", "segment", "branche"]
    ] = Field(None, description="Achse der Auswertung (fuer set_group_by): "
                                "Zeitachse oder Sachdimension.")
    kategorie: Optional[str] = Field(
        None, description="'hardware', 'software' oder 'service' "
                          "(fuer set_kategorie_filter)."
    )
    quartal: Optional[int] = Field(
        None, description="Quartal 1-4 (fuer set_quartal_filter). "
                          "0 oder null hebt den Filter auf."
    )
    nur_werktage: Optional[bool] = Field(
        None, description="True = Wochenenden ausblenden (fuer set_workday_filter)."
    )
    series_key: Optional[str] = Field(
        None, description="Schluessel der einzublendenden Reihe, z.B. 'kosten' oder 'gewinn'."
    )
    kpi_name: Optional[str] = Field(None, description="Name der neuen KPI, z.B. 'gewinn'.")
    kpi_expression: Optional[str] = Field(
        None, description="Definition der KPI, z.B. 'umsatz - kosten'."
    )
    reply: str = Field(
        max_length=200,
        description=(
            "EIN kurzer, vollstaendiger deutscher Satz, der nur die Aktion "
            "bestaetigt. Keine Zahlen, keine Betraege, keine Datenwerte -- "
            "diese stehen im Diagramm. Muss mit einem Punkt enden."
        ),
    )
