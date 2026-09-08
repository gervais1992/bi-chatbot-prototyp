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
                 base: dict[str, list[float]]) -> go.Figure:
    fig = go.Figure()

    for i, s in enumerate(ctx.series):
        values = sem.compute_series_values(s.key, base, ctx)
        if i == 0 and ctx.chart_type == "bar":
            fig.add_trace(go.Bar(x=labels, y=values, name=s.label,
                                 marker_color=s.color, opacity=0.9))
        else:
            fig.add_trace(go.Scatter(x=labels, y=values, name=s.label,
                                     mode="lines+markers",
                                     line=dict(color=s.color, width=2.5)))

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
