"""
dashboards/experiment_dashboard.py
------------------------------------
Reusable Plotly chart-building functions consumed by app.py. Kept separate
from app.py so charts can also be unit-tested or reused in the PDF report
generator without importing Streamlit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

CONTROL_COLOR = "#6B7280"
TREATMENT_COLOR = "#4F46E5"
GOOD_COLOR = "#16A34A"
BAD_COLOR = "#DC2626"
WARN_COLOR = "#D97706"


def traffic_split_pie(control_n: int, treatment_n: int) -> go.Figure:
    fig = go.Figure(data=[go.Pie(
        labels=["Control", "Treatment"],
        values=[control_n, treatment_n],
        hole=0.55,
        marker=dict(colors=[CONTROL_COLOR, TREATMENT_COLOR]),
    )])
    fig.update_layout(title="Traffic Split", height=350, margin=dict(t=50, b=10, l=10, r=10))
    return fig


def lift_chart(control_mean: float, treatment_mean: float, metric_name: str) -> go.Figure:
    fig = go.Figure(data=[go.Bar(
        x=["Control", "Treatment"],
        y=[control_mean, treatment_mean],
        marker_color=[CONTROL_COLOR, TREATMENT_COLOR],
        text=[f"{control_mean:.4f}", f"{treatment_mean:.4f}"],
        textposition="outside",
    )])
    fig.update_layout(title=f"Control vs Treatment — {metric_name}", height=380,
                       margin=dict(t=50, b=10, l=10, r=10), yaxis_title=metric_name)
    return fig


def confidence_interval_plot(diff: float, ci_lower: float, ci_upper: float, metric_name: str,
                              confidence_label: str = "95%") -> go.Figure:
    is_sig = ci_lower > 0 or ci_upper < 0
    color = GOOD_COLOR if (is_sig and diff > 0) else (BAD_COLOR if (is_sig and diff < 0) else WARN_COLOR)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[ci_lower, ci_upper], y=["Difference (Treatment - Control)"] * 2,
        mode="lines", line=dict(color=color, width=6), showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=[diff], y=["Difference (Treatment - Control)"], mode="markers",
        marker=dict(color=color, size=14, symbol="diamond"), showlegend=False,
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title=f"{confidence_label} Confidence Interval — {metric_name}",
        height=250, margin=dict(t=50, b=30, l=10, r=10), xaxis_title="Absolute difference",
    )
    return fig


def p_value_gauge(p_value: float) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=p_value,
        number={"valueformat": ".4f"},
        title={"text": "P-Value"},
        gauge={
            "axis": {"range": [0, 1]},
            "bar": {"color": "#111827"},
            "steps": [
                {"range": [0, 0.01], "color": "#bbf7d0"},
                {"range": [0.01, 0.05], "color": "#d9f99d"},
                {"range": [0.05, 1], "color": "#fee2e2"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "thickness": 0.9, "value": 0.05},
        },
    ))
    fig.update_layout(height=280, margin=dict(t=50, b=10, l=20, r=20))
    return fig


def funnel_chart(stages: list[str], values: list[int]) -> go.Figure:
    fig = go.Figure(go.Funnel(y=stages, x=values, marker=dict(color=TREATMENT_COLOR)))
    fig.update_layout(title="Application Funnel", height=400, margin=dict(t=50, b=10, l=10, r=10))
    return fig


def trend_chart(df: pd.DataFrame, x: str, y: str, color: str, title: str) -> go.Figure:
    fig = px.line(df, x=x, y=y, color=color, markers=True,
                   color_discrete_map={"control": CONTROL_COLOR, "treatment": TREATMENT_COLOR})
    fig.update_layout(title=title, height=350, margin=dict(t=50, b=10, l=10, r=10))
    return fig


def box_plot(control: np.ndarray, treatment: np.ndarray, metric_name: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Box(y=control, name="Control", marker_color=CONTROL_COLOR))
    fig.add_trace(go.Box(y=treatment, name="Treatment", marker_color=TREATMENT_COLOR))
    fig.update_layout(title=f"Distribution — {metric_name}", height=380, margin=dict(t=50, b=10, l=10, r=10))
    return fig


def histogram(control: np.ndarray, treatment: np.ndarray, metric_name: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=control, name="Control", marker_color=CONTROL_COLOR, opacity=0.6))
    fig.add_trace(go.Histogram(x=treatment, name="Treatment", marker_color=TREATMENT_COLOR, opacity=0.6))
    fig.update_layout(barmode="overlay", title=f"Histogram — {metric_name}", height=380,
                       margin=dict(t=50, b=10, l=10, r=10))
    return fig


def guardrail_bar_chart(guardrail_results: list) -> go.Figure:
    names = [g.metric_name for g in guardrail_results]
    rel_changes = [g.relative_change_pct or 0 for g in guardrail_results]
    colors = [BAD_COLOR if g.is_regression else GOOD_COLOR for g in guardrail_results]
    fig = go.Figure(go.Bar(x=names, y=rel_changes, marker_color=colors,
                            text=[f"{v:+.1f}%" for v in rel_changes], textposition="outside"))
    fig.add_hline(y=0, line_color="gray")
    fig.update_layout(title="Guardrail Relative Change (Treatment vs Control)", height=380,
                       margin=dict(t=50, b=10, l=10, r=10), yaxis_title="Relative change (%)")
    return fig


def srm_allocation_chart(observed_control: int, observed_treatment: int, expected_control_ratio: float) -> go.Figure:
    total = observed_control + observed_treatment
    expected_control = total * expected_control_ratio
    expected_treatment = total * (1 - expected_control_ratio)
    fig = go.Figure(data=[
        go.Bar(name="Expected", x=["Control", "Treatment"], y=[expected_control, expected_treatment],
               marker_color="#D1D5DB"),
        go.Bar(name="Observed", x=["Control", "Treatment"], y=[observed_control, observed_treatment],
               marker_color=TREATMENT_COLOR),
    ])
    fig.update_layout(barmode="group", title="Expected vs Observed Allocation", height=380,
                       margin=dict(t=50, b=10, l=10, r=10))
    return fig


def srm_heatmap(experiments_summary: pd.DataFrame) -> go.Figure:
    """experiments_summary needs columns: experiment_id, deviation_pp"""
    fig = go.Figure(data=go.Heatmap(
        z=[experiments_summary["deviation_pp"].tolist()],
        x=experiments_summary["experiment_id"].tolist(),
        y=["Allocation deviation (pp)"],
        colorscale="RdYlGn_r",
        text=[[f"{v:.2f}pp" for v in experiments_summary["deviation_pp"]]],
        texttemplate="%{text}",
    ))
    fig.update_layout(title="SRM Heatmap — Allocation Deviation Across Experiments", height=250,
                       margin=dict(t=50, b=10, l=10, r=10))
    return fig
