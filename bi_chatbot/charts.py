"""Visualisierungs-Modul.

Baut aus dem `AnalysisContext`, den Achsenbeschriftungen und den geladenen
Werten eine Plotly-Figur. Die erste Reihe folgt dem gewaehlten Diagrammtyp
(Linie/Saeulen); weitere Reihen (z.B. Kosten, Gewinn) werden als ueberlagerte
Linien dargestellt -- so wie im Beispieldialog des Professors.
"""
from __future__ import annotations

import plotly.graph_objects as go

from . import semantic_layer as sem
from .state import AnalysisContext


def build_figure(ctx: AnalysisContext, labels: list[str],
                 base: dict[str, list[float]],
                 prognose: set[str] | None = None) -> go.Figure:
    """Baut die Figur. `prognose` enthaelt die Achsenwerte, die geschaetzt sind.

    Prognosewerte werden optisch klar abgesetzt, damit sie nicht mit
    Messwerten verwechselt werden koennen.
    """
    fig = go.Figure()
    prognose = prognose or set()
    ist_prognose = [lab in prognose for lab in labels]

    for i, s in enumerate(ctx.series):
        values = sem.compute_series_values(s.key, base, ctx)
        if i == 0 and ctx.chart_type == "bar":
            fig.add_trace(go.Bar(
                x=labels, y=values, name=s.label, marker_color=s.color,
                marker_pattern_shape=["/" if p else "" for p in ist_prognose],
                opacity=0.9))
        else:
            fig.add_trace(go.Scatter(x=labels, y=values, name=s.label,
                                     mode="lines+markers",
                                     line=dict(color=s.color, width=2.5)))

    # Prognosebereich hervorheben
    if prognose:
        erste = min(i for i, p in enumerate(ist_prognose) if p)
        fig.add_vrect(x0=erste - 0.5, x1=len(labels) - 0.5,
                      fillcolor="#888888", opacity=0.10, line_width=0,
                      annotation_text="Prognose",
                      annotation_position="top left")

    grouping = sem.GROUPINGS.get(ctx.group_by)
    fig.update_layout(
        template="plotly_white",
        height=380,
        margin=dict(l=40, r=20, t=30, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis_title=grouping.label if grouping else None,
        yaxis_title="EUR",
        bargap=0.35,
    )
    # Kategorische Achse: Reihenfolge aus der Abfrage beibehalten
    fig.update_xaxes(type="category")
    return fig
