"""
scripts/generate_reports.py
------------------------------
Generates the two PDF deliverables referenced in the project spec:

  reports/experiment_report.pdf  — full multi-experiment readout report
  reports/ship_decision.pdf      — one-page-per-experiment ship/no-ship memo

Both are built entirely from ExperimentReadout / Recommendation objects
produced by experiment_engine.py and recommendation_engine.py — no numbers
are typed directly into this file.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)

import config
import database
from experiment_engine import run_full_readout
from recommendation_engine import make_recommendation

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1Custom", parent=styles["Heading1"], textColor=colors.HexColor("#1F2937")))
styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], textColor=colors.HexColor("#374151")))
styles.add(ParagraphStyle(name="BodySmall", parent=styles["Normal"], fontSize=9, leading=12))
styles.add(ParagraphStyle(name="Reasoning", parent=styles["Normal"], fontSize=9.5, leading=13, leftIndent=10))

DECISION_COLOR = {
    "Ship": colors.HexColor("#16A34A"),
    "No Ship": colors.HexColor("#DC2626"),
    "Continue": colors.HexColor("#D97706"),
    "Pause": colors.HexColor("#D97706"),
    "Rollback": colors.HexColor("#374151"),
}


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table(rows, colWidths=[1.7 * inch, 4.8 * inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
    ]))
    return t


def _stats_table(result) -> Table:
    data = [
        ["Field", "Value"],
        ["Test used", result.test_used],
        ["Control N / mean", f"{result.control_n:,} / {result.control_mean}"],
        ["Treatment N / mean", f"{result.treatment_n:,} / {result.treatment_mean}"],
        ["Absolute difference", str(result.absolute_diff)],
        ["Relative difference", f"{result.relative_diff_pct}%" if result.relative_diff_pct is not None else "N/A"],
        ["Standard error", str(result.std_error)],
        ["Test statistic", str(result.z_or_t_stat)],
        ["P-value", str(result.p_value)],
        ["95% CI", f"[{result.ci_95_lower}, {result.ci_95_upper}]"],
        ["99% CI", f"[{result.ci_99_lower}, {result.ci_99_upper}]"],
        ["Margin of error (95%)", str(result.margin_of_error_95)],
        ["Significant @95% / @99%", f"{result.is_significant_95} / {result.is_significant_99}"],
        ["Statistical power", str(result.statistical_power)],
        ["Min. detectable effect", str(result.minimum_detectable_effect)],
        ["Low-sample warning", str(result.low_sample_warning)],
    ]
    t = Table(data, colWidths=[1.9 * inch, 4.6 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _guardrail_table(guardrail_results) -> Table:
    data = [["Metric", "Control", "Treatment", "Rel. change", "P-value", "Regression?"]]
    for g in guardrail_results:
        data.append([
            g.metric_name, f"{g.control_rate:.4f}", f"{g.treatment_rate:.4f}",
            f"{g.relative_change_pct:+.1f}%" if g.relative_change_pct is not None else "N/A",
            f"{g.p_value:.4f}", "YES" if g.is_regression else "no",
        ])
    t = Table(data, colWidths=[1.5 * inch, 0.9 * inch, 0.95 * inch, 0.95 * inch, 0.85 * inch, 1.0 * inch])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, g in enumerate(guardrail_results, start=1):
        if g.is_regression:
            style.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#DC2626")))
            style.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def _experiment_section(readout, recommendation) -> list:
    meta = readout.meta
    story = []
    story.append(Paragraph(meta["experiment_name"], styles["H1Custom"]))
    story.append(Paragraph(f"Experiment ID: {readout.experiment_id}", styles["BodySmall"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Executive Summary", styles["H2Custom"]))
    decision_color = DECISION_COLOR.get(recommendation.decision, colors.black)
    decision_style = ParagraphStyle(name="Decision", parent=styles["Normal"], fontSize=13,
                                     textColor=decision_color, fontName="Helvetica-Bold")
    story.append(Paragraph(f"DECISION: {recommendation.decision}", decision_style))
    story.append(Paragraph(recommendation.headline, styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(_kv_table([
        ["Business Goal", meta["business_goal"]],
        ["Hypothesis", meta["hypothesis"]],
        ["Owner", meta["owner"]],
        ["Experiment Window", f"{meta['start_date']} to {meta['end_date']}"],
        ["Decision Date", meta.get("decision_date", "N/A")],
        ["Traffic", f"Control n={readout.control_n:,} / Treatment n={readout.treatment_n:,}"],
    ]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Primary Metric — Statistical Readout", styles["H2Custom"]))
    story.append(_stats_table(readout.primary_result))
    story.append(Spacer(1, 10))

    if readout.secondary_results:
        story.append(Paragraph("Secondary Metrics", styles["H2Custom"]))
        for sec in readout.secondary_results:
            story.append(Paragraph(f"<b>{sec.metric}</b>", styles["Normal"]))
            story.append(_stats_table(sec))
            story.append(Spacer(1, 8))

    story.append(Paragraph("Sample Ratio Mismatch (SRM) Check", styles["H2Custom"]))
    srm = readout.srm
    srm_flag_style = ParagraphStyle(name="SRMFlag", parent=styles["Normal"], fontSize=10,
                                     textColor=colors.HexColor("#DC2626") if srm.srm_detected else colors.HexColor("#16A34A"),
                                     fontName="Helvetica-Bold")
    story.append(Paragraph(
        f"{'SRM DETECTED' if srm.srm_detected else 'No SRM detected'} (severity: {srm.severity})", srm_flag_style
    ))
    story.append(_kv_table([
        ["Expected split", f"{srm.expected_control_ratio:.0%} / {srm.expected_treatment_ratio:.0%}"],
        ["Observed split", f"{srm.observed_control_ratio:.1%} / {srm.observed_treatment_ratio:.1%}"],
        ["Chi-square / p-value", f"{srm.chi_square_statistic} / {srm.p_value}"],
        ["Recommendation", srm.recommendation],
    ]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Guardrail Metrics", styles["H2Custom"]))
    if readout.guardrail_results:
        story.append(_guardrail_table(readout.guardrail_results))
    else:
        story.append(Paragraph("No guardrail results available for this experiment.", styles["Normal"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Recommendation & Reasoning", styles["H2Custom"]))
    for line in recommendation.reasoning:
        story.append(Paragraph(f"&bull; {line}", styles["Reasoning"]))

    return story


def generate_full_report(output_path: str) -> None:
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    story = []
    story.append(Paragraph("PlaceMux Growth Experimentation — Experiment Report", styles["Title"]))
    story.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"All figures computed live from placemux.db", styles["BodySmall"],
    ))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#E5E7EB")))
    story.append(Spacer(1, 12))

    experiments = database.list_experiments()
    for i, row in experiments.iterrows():
        readout = run_full_readout(row["experiment_id"])
        rec = make_recommendation(readout)
        story.extend(_experiment_section(readout, rec))
        if i < len(experiments) - 1:
            story.append(PageBreak())

    doc.build(story)
    print(f"Wrote {output_path}")


def generate_ship_decision_memo(output_path: str) -> None:
    """A condensed, leadership-facing memo: one row per experiment with the
    decision and the one-line reason, plus the guardrail/SRM gates."""
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    story = []
    story.append(Paragraph("PlaceMux — Ship / No-Ship Decision Memo", styles["Title"]))
    story.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", styles["BodySmall"],
    ))
    story.append(Spacer(1, 10))

    experiments = database.list_experiments()
    header = ["Experiment", "Primary Metric Lift", "P-value", "SRM", "Guardrails", "Decision"]
    data = [header]
    row_colors = [colors.HexColor("#111827")]
    for _, row in experiments.iterrows():
        readout = run_full_readout(row["experiment_id"])
        rec = make_recommendation(readout)
        n_reg = sum(1 for g in readout.guardrail_results if g.is_regression)
        data.append([
            row["experiment_name"],
            f"{readout.primary_result.relative_diff_pct:+.2f}%" if readout.primary_result.relative_diff_pct is not None else "N/A",
            f"{readout.primary_result.p_value:.4f}",
            "FLAGGED" if readout.srm.srm_detected else "clean",
            f"{n_reg} regression(s)" if n_reg else "clean",
            rec.decision,
        ])
        row_colors.append(DECISION_COLOR.get(rec.decision, colors.black))

    t = Table(data, colWidths=[1.7 * inch, 1.0 * inch, 0.75 * inch, 0.75 * inch, 1.1 * inch, 0.9 * inch])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
    ]
    for i in range(1, len(data)):
        style.append(("TEXTCOLOR", (5, i), (5, i), row_colors[i]))
        style.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Detailed Reasoning", styles["H2Custom"]))
    for _, row in experiments.iterrows():
        readout = run_full_readout(row["experiment_id"])
        rec = make_recommendation(readout)
        decision_color = DECISION_COLOR.get(rec.decision, colors.black)
        story.append(Paragraph(
            f"{row['experiment_name']} — <font color='#{decision_color.hexval()[2:]}'><b>{rec.decision}</b></font>",
            styles["H2Custom"],
        ))
        for line in rec.reasoning:
            story.append(Paragraph(f"&bull; {line}", styles["Reasoning"]))
        story.append(Spacer(1, 8))

    doc.build(story)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    out_report = str(config.REPORTS_DIR / "experiment_report.pdf")
    out_memo = str(config.REPORTS_DIR / "ship_decision.pdf")
    generate_full_report(out_report)
    generate_ship_decision_memo(out_memo)
