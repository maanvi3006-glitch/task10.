"""
app.py
-------
PlaceMux Growth Experimentation Analytics Platform — Streamlit dashboard.

Run with:
    streamlit run app.py

Pages (sidebar navigation):
    Overview            - portfolio-level KPIs across all experiments
    Experiment Summary  - traffic split, primary KPI, ship/no-ship decision
    Statistical Analysis- CI, p-values, power, distributions
    Guardrails          - guardrail regression monitoring + trend charts
    SRM                 - sample ratio mismatch detection
    Recommendation      - full ship/no-ship reasoning
    Experiment Log       - historical decision log / learnings
    Validation          - data-quality checks tied to every metric
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import database
import validation as validation_module
from dashboards import experiment_dashboard as charts
from experiment_engine import run_full_readout, _get_metric_arrays
from recommendation_engine import make_recommendation
from experiment_logger import log_experiment

st.set_page_config(page_title="PlaceMux Growth Experimentation Platform", layout="wide",
                    page_icon="📈")

# --------------------------------------------------------------------------
# Sidebar — global filters
# --------------------------------------------------------------------------
st.sidebar.title("📈 PlaceMux Growth Analytics")

dark_mode = st.sidebar.toggle("Dark mode", value=False)
if dark_mode:
    st.markdown(
        """
        <style>
        .stApp { background-color: #0E1117; color: #E5E7EB; }
        </style>
        """,
        unsafe_allow_html=True,
    )

if not Path(database.config.DB_PATH).exists():
    st.sidebar.warning("Database not found. Building it now...")
    database.build_database(force=True)
    st.sidebar.success("Database built.")

experiments_df = database.list_experiments()
if experiments_df.empty:
    st.error("No experiments found in the database. Run `python database.py` after `python scripts/generate_data.py`.")
    st.stop()

experiment_id = st.sidebar.selectbox(
    "Experiment", experiments_df["experiment_id"] + " — " + experiments_df["experiment_name"],
)
experiment_id = experiment_id.split(" — ")[0]

page = st.sidebar.radio(
    "Page",
    ["Overview", "Experiment Summary", "Statistical Analysis", "Guardrails",
     "SRM", "Recommendation", "Experiment Log", "Validation"],
)

date_range = st.sidebar.date_input("Date range filter (informational)", value=())
st.sidebar.caption("Date filtering narrows chart windows; core statistics always use the full experiment period for validity.")

st.sidebar.divider()
st.sidebar.caption("Data: SQLite (placemux.db) · Stats: SciPy / Statsmodels · Charts: Plotly")


@st.cache_data(show_spinner=False, ttl=60)
def _cached_readout(exp_id: str):
    r = run_full_readout(exp_id)
    return r


def get_readout(exp_id: str):
    return run_full_readout(exp_id)  # not cached: dataclasses with nested objects; cheap enough to recompute


readout = get_readout(experiment_id)
recommendation = make_recommendation(readout)

DECISION_COLORS = {
    "Ship": "🟢", "No Ship": "🔴", "Continue": "🟡", "Pause": "🟠", "Rollback": "⚫",
}

# --------------------------------------------------------------------------
# Page: Overview
# --------------------------------------------------------------------------
if page == "Overview":
    st.title("Growth Experimentation — Portfolio Overview")
    st.caption("Every number below is computed live from the SQLite database — nothing is hard-coded.")

    cols = st.columns(len(experiments_df))
    summary_rows = []
    for i, row in experiments_df.iterrows():
        eid = row["experiment_id"]
        r = get_readout(eid)
        rec = make_recommendation(r)
        summary_rows.append({
            "experiment_id": eid,
            "experiment_name": row["experiment_name"],
            "primary_metric": r.primary_result.metric,
            "relative_lift_pct": r.primary_result.relative_diff_pct,
            "p_value": r.primary_result.p_value,
            "srm_flagged": r.srm.srm_detected,
            "guardrail_regressions": sum(1 for g in r.guardrail_results if g.is_regression),
            "decision": rec.decision,
        })

    summary_df = pd.DataFrame(summary_rows)

    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Experiments Tracked", len(summary_df))
    kpi_cols[1].metric("Shipped", int((summary_df.decision == "Ship").sum()))
    kpi_cols[2].metric("No Ship / Rollback", int(summary_df.decision.isin(["No Ship", "Rollback"]).sum()))
    kpi_cols[3].metric("SRM Flags", int(summary_df.srm_flagged.sum()))

    st.subheader("Experiment Portfolio")
    display_df = summary_df.copy()
    display_df["decision"] = display_df["decision"].apply(lambda d: f"{DECISION_COLORS.get(d,'')} {d}")
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("SRM Heatmap Across Portfolio")
    dev_rows = []
    for i, row in experiments_df.iterrows():
        eid = row["experiment_id"]
        r = get_readout(eid)
        total = r.srm.observed_control_n + r.srm.observed_treatment_n
        dev_pp = abs(r.srm.observed_control_ratio - r.srm.expected_control_ratio) * 100
        dev_rows.append({"experiment_id": eid, "deviation_pp": dev_pp})
    dev_df = pd.DataFrame(dev_rows)
    st.plotly_chart(charts.srm_heatmap(dev_df), use_container_width=True)

    csv_buf = io.StringIO()
    summary_df.to_csv(csv_buf, index=False)
    st.download_button("Export Portfolio CSV", csv_buf.getvalue(), file_name="experiment_portfolio.csv",
                        mime="text/csv")

# --------------------------------------------------------------------------
# Page: Experiment Summary
# --------------------------------------------------------------------------
elif page == "Experiment Summary":
    st.title(f"Experiment Summary — {readout.meta['experiment_name']}")
    st.caption(readout.meta["hypothesis"])

    meta_cols = st.columns(4)
    meta_cols[0].markdown(f"**Owner**\n\n{readout.meta['owner']}")
    meta_cols[1].markdown(f"**Start**\n\n{readout.meta['start_date']}")
    meta_cols[2].markdown(f"**End**\n\n{readout.meta['end_date']}")
    meta_cols[3].markdown(f"**Decision date**\n\n{readout.meta['decision_date']}")

    st.info(f"**Business goal:** {readout.meta['business_goal']}")

    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Control N", f"{readout.control_n:,}")
    kpi_cols[1].metric("Treatment N", f"{readout.treatment_n:,}")
    kpi_cols[2].metric(f"Primary metric ({readout.primary_result.metric})",
                        f"{readout.primary_result.treatment_mean:.4f}",
                        delta=f"{readout.primary_result.relative_diff_pct:+.2f}%")
    kpi_cols[3].metric("P-value", f"{readout.primary_result.p_value:.4f}")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.traffic_split_pie(readout.control_n, readout.treatment_n),
                         use_container_width=True)
    with c2:
        st.plotly_chart(charts.lift_chart(readout.primary_result.control_mean,
                                           readout.primary_result.treatment_mean,
                                           readout.primary_result.metric),
                         use_container_width=True)

    st.subheader("Application Funnel (Treatment Arm)")
    with database.get_connection() as conn:
        funnel_df = pd.read_sql(
            """
            SELECT ea.variant, COUNT(DISTINCT ea.user_id) AS assigned,
                   COUNT(DISTINCT CASE WHEN ev.event_type='conversion' THEN ea.user_id END) AS converted
            FROM ExperimentAssignments ea
            LEFT JOIN ExperimentEvents ev ON ev.experiment_id = ea.experiment_id AND ev.user_id = ea.user_id
            WHERE ea.experiment_id = ?
            GROUP BY ea.variant
            """, conn, params=(experiment_id,),
        )
    treatment_row = funnel_df[funnel_df.variant == "treatment"]
    if not treatment_row.empty:
        assigned = int(treatment_row["assigned"].iloc[0])
        converted = int(treatment_row["converted"].iloc[0])
        st.plotly_chart(charts.funnel_chart(["Assigned", "Converted"], [assigned, converted]),
                         use_container_width=True)

    st.subheader(f"{DECISION_COLORS.get(recommendation.decision,'')} Decision: {recommendation.decision}")
    st.write(recommendation.headline)

# --------------------------------------------------------------------------
# Page: Statistical Analysis
# --------------------------------------------------------------------------
elif page == "Statistical Analysis":
    st.title("Statistical Analysis")

    all_metrics = [readout.primary_result] + readout.secondary_results
    metric_names = [m.metric for m in all_metrics]
    selected_metric = st.selectbox("Metric", metric_names)
    metric_result = next(m for m in all_metrics if m.metric == selected_metric)

    st.subheader(f"Test used: {metric_result.test_used}")

    cols = st.columns(5)
    cols[0].metric("Control mean", metric_result.control_mean)
    cols[1].metric("Treatment mean", metric_result.treatment_mean)
    cols[2].metric("Absolute diff", metric_result.absolute_diff)
    cols[3].metric("Relative diff", f"{metric_result.relative_diff_pct}%" if metric_result.relative_diff_pct is not None else "N/A")
    cols[4].metric("Std. error", metric_result.std_error)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            charts.confidence_interval_plot(metric_result.absolute_diff, metric_result.ci_95_lower,
                                             metric_result.ci_95_upper, selected_metric, "95%"),
            use_container_width=True,
        )
        st.plotly_chart(
            charts.confidence_interval_plot(metric_result.absolute_diff, metric_result.ci_99_lower,
                                             metric_result.ci_99_upper, selected_metric, "99%"),
            use_container_width=True,
        )
    with c2:
        st.plotly_chart(charts.p_value_gauge(metric_result.p_value), use_container_width=True)
        power_cols = st.columns(2)
        power_cols[0].metric("Statistical Power", metric_result.statistical_power if metric_result.statistical_power is not None else "N/A")
        power_cols[1].metric("Min. Detectable Effect", metric_result.minimum_detectable_effect if metric_result.minimum_detectable_effect is not None else "N/A")
        if metric_result.low_sample_warning:
            st.warning(f"Sample size below the {database.config.MIN_SAMPLE_PER_ARM}/arm threshold — treat significance with caution.")

    st.subheader("Distribution — Control vs Treatment")
    control_arr, treatment_arr = _get_metric_arrays(experiment_id, selected_metric)
    dc1, dc2 = st.columns(2)
    with dc1:
        st.plotly_chart(charts.box_plot(control_arr, treatment_arr, selected_metric), use_container_width=True)
    with dc2:
        st.plotly_chart(charts.histogram(control_arr, treatment_arr, selected_metric), use_container_width=True)

    with st.expander("Full statistical readout (all fields)"):
        st.json(metric_result.to_dict())

# --------------------------------------------------------------------------
# Page: Guardrails
# --------------------------------------------------------------------------
elif page == "Guardrails":
    st.title("Guardrail Monitoring")
    st.caption("A guardrail only counts as a regression if the change is BOTH statistically significant "
               "and in the harmful direction.")

    if not readout.guardrail_results:
        st.warning("No guardrail results computed for this experiment (check guardrail_metrics mapping).")
    else:
        g_df = pd.DataFrame([g.to_dict() for g in readout.guardrail_results])
        display_g = g_df.copy()
        display_g["alert_level"] = display_g.apply(
            lambda r: f"🔴 {r['alert_level']}" if r["is_regression"] else f"🟢 {r['alert_level']}", axis=1
        )
        st.dataframe(display_g, use_container_width=True, hide_index=True)

        st.plotly_chart(charts.guardrail_bar_chart(readout.guardrail_results), use_container_width=True)

        regressions = [g for g in readout.guardrail_results if g.is_regression]
        if regressions:
            for g in regressions:
                st.error(f"**{g.metric_name}** regressed {g.relative_change_pct:+.1f}% "
                          f"(p={g.p_value:.4f}) — control {g.control_rate:.4f} → treatment {g.treatment_rate:.4f}")
        else:
            st.success("No statistically significant guardrail regressions detected.")

    st.subheader("Guardrail Evaluation History")
    hist = database.get_guardrail_history(experiment_id)
    if hist.empty:
        st.info("No historical guardrail evaluations logged yet for this experiment.")
    else:
        st.dataframe(hist, use_container_width=True, hide_index=True)
        trend_source = hist.copy()
        trend_source["evaluated_at"] = pd.to_datetime(trend_source["evaluated_at"])
        import plotly.express as px
        fig = px.line(trend_source, x="evaluated_at", y="relative_change", color="metric_name",
                       markers=True, title="Guardrail Relative Change Over Evaluations")
        st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------
# Page: SRM
# --------------------------------------------------------------------------
elif page == "SRM":
    st.title("Sample Ratio Mismatch (SRM) Detection")
    srm = readout.srm

    cols = st.columns(4)
    cols[0].metric("Expected split", f"{srm.expected_control_ratio:.0%} / {srm.expected_treatment_ratio:.0%}")
    cols[1].metric("Observed split", f"{srm.observed_control_ratio:.1%} / {srm.observed_treatment_ratio:.1%}")
    cols[2].metric("Chi-square", srm.chi_square_statistic)
    cols[3].metric("P-value", srm.p_value)

    if srm.srm_detected:
        st.error(f"⚠️ SRM DETECTED — severity: **{srm.severity}**")
    else:
        st.success("✅ No SRM detected — allocation matches the intended randomization ratio.")

    st.write(srm.recommendation)

    st.plotly_chart(
        charts.srm_allocation_chart(srm.observed_control_n, srm.observed_treatment_n, srm.expected_control_ratio),
        use_container_width=True,
    )

    st.subheader("SRM Across All Experiments")
    dev_rows = []
    for i, row in experiments_df.iterrows():
        eid = row["experiment_id"]
        r = get_readout(eid)
        dev_pp = abs(r.srm.observed_control_ratio - r.srm.expected_control_ratio) * 100
        dev_rows.append({"experiment_id": eid, "deviation_pp": dev_pp})
    st.plotly_chart(charts.srm_heatmap(pd.DataFrame(dev_rows)), use_container_width=True)

    with st.expander("Full SRM result"):
        st.json(srm.to_dict())

# --------------------------------------------------------------------------
# Page: Recommendation
# --------------------------------------------------------------------------
elif page == "Recommendation":
    st.title("Ship / No-Ship Recommendation")

    decision_icon = DECISION_COLORS.get(recommendation.decision, "")
    st.header(f"{decision_icon} {recommendation.decision}")
    st.subheader(recommendation.headline)
    st.caption(f"Confidence level: {recommendation.confidence_level}")

    st.subheader("Why")
    for line in recommendation.reasoning:
        st.markdown(f"- {line}")

    if st.button("Log this decision to the Experiment Log"):
        log_experiment(readout, recommendation)
        st.success(f"Logged decision '{recommendation.decision}' for {experiment_id}.")

    report_md = io.StringIO()
    report_md.write(f"# Experiment Readout — {readout.meta['experiment_name']}\n\n")
    report_md.write(f"**Decision:** {recommendation.decision}\n\n**Headline:** {recommendation.headline}\n\n")
    report_md.write("## Reasoning\n\n")
    for line in recommendation.reasoning:
        report_md.write(f"- {line}\n")
    st.download_button("Export Recommendation (Markdown)", report_md.getvalue(),
                        file_name=f"{experiment_id}_recommendation.md", mime="text/markdown")

# --------------------------------------------------------------------------
# Page: Experiment Log
# --------------------------------------------------------------------------
elif page == "Experiment Log":
    st.title("Experiment Log & Learning History")

    logs_df = database.get_experiment_logs()
    if logs_df.empty:
        st.info("No experiments logged yet. Visit the Recommendation page and click "
                "'Log this decision' for each experiment, or run `python experiment_logger.py`.")
    else:
        for _, log in logs_df.iterrows():
            with st.expander(f"{DECISION_COLORS.get(log['decision'],'')} {log['experiment_name']} — {log['decision']} ({log['logged_at'][:10]})"):
                st.markdown(f"**Owner:** {log['owner']}")
                st.markdown(f"**Objective:** {log['objective']}")
                st.markdown(f"**Hypothesis:** {log['hypothesis']}")
                st.markdown(f"**Primary metric result:** {log['primary_metric_result']}")
                st.markdown(f"**Reasoning:** {log['reasoning']}")
                st.markdown(f"**Lessons learned:** {log['lessons_learned']}")
                st.markdown(f"**Next experiment:** {log['next_experiment']}")

        csv_buf = io.StringIO()
        logs_df.to_csv(csv_buf, index=False)
        st.download_button("Export Experiment Log CSV", csv_buf.getvalue(), file_name="experiment_log.csv",
                            mime="text/csv")

# --------------------------------------------------------------------------
# Page: Validation
# --------------------------------------------------------------------------
elif page == "Validation":
    st.title("Data Validation & Metric Traceability")
    st.caption("Every metric must trace back to a source table, SQL query and formula. "
               "Missing data is flagged, never estimated.")

    metric_choice = st.selectbox("Metric", list(validation_module.METRIC_METADATA.keys()))
    meta = validation_module.METRIC_METADATA[metric_choice]
    st.markdown(f"**Source table:** `{meta['source_table']}`")
    st.code(meta["sql_query"], language="sql")
    st.markdown(f"**Formula:** {meta['formula']}")
    st.markdown(f"**Primary key:** `{meta['primary_key']}`")

    st.subheader("Table-Level Validation Report")
    with st.spinner("Running validation checks..."):
        reports = validation_module.run_all_validations()

    rows = []
    for table, r in reports.items():
        rows.append({
            "table": table,
            "row_count": r.row_count,
            "missing_value_cols": len(r.missing_value_counts),
            "duplicate_rows": r.duplicate_rows,
            "duplicate_pk_rows": r.duplicate_primary_keys,
            "outlier_cols": len(r.outlier_counts),
            "passed": "✅" if r.passed else "❌",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader(f"Cross-Table Consistency — {experiment_id}")
    issues = validation_module.validate_experiment_consistency(experiment_id)
    if issues:
        for issue in issues:
            st.error(issue)
    else:
        st.success("No consistency issues found for this experiment.")
