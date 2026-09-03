"""Streamlit Demo UI for AI Finance Controller.

Provides interactive upload flow with schema auto-mapping, data quality pre-check report cards,
PII masking, financial expense summaries, human review queue, and audit trail inspection.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st
from config.settings import DATA_DIR, OUTPUTS_DIR
from src.data_quality import check_data_quality
from src.pipeline import run_reconciliation_pipeline
from src.review import ReviewQueue
from src.schema_mapper import apply_mapping_and_normalize, map_columns

# Page configuration
st.set_page_config(
    page_title="AI Finance Controller | Razorpay Buildathon",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for rich aesthetics
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    
    .sub-header {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }
    
    .metric-card {
        background-color: #f8fafc;
        background: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }
    
    .metric-title {
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        color: #94a3b8 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    .metric-value {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #ffffff !important;
        margin-top: 0.4rem;
    }

    .fee-card {
        background: #0f172a !important;
        border: 1px solid #ef4444 !important;
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1.5rem;
    }

    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }

    .badge-calibrated { background-color: #dcfce7; color: #166534; }
    .badge-overconfident { background-color: #fee2e2; color: #991b1b; }
    .badge-underconfident { background-color: #fef3c7; color: #92400e; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header
st.markdown('<div class="main-header">⚡ AI Finance Controller</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Multi-Source Reconciliation & Schema Auto-Mapper Engine | Track 04 Build</div>', unsafe_allow_html=True)

# Target Schema definitions
TARGET_SCHEMAS = {
    "bank_statement": ["txn_id", "date", "amount", "reference_id", "description"],
    "settlement_report": ["settlement_id", "date", "gross_amount", "fee", "net_amount", "reference_id", "order_id"],
    "internal_ledger": ["order_id", "date", "amount", "customer_ref", "status"],
}

# Sidebar Controls & File Uploaders
st.sidebar.title("📁 Upload Custom CSV Files")
st.sidebar.markdown("Upload local CSV files or use pre-loaded datasets:")

uploaded_bank = st.sidebar.file_uploader("1. Bank Statement CSV", type=["csv"], key="bank_up")
uploaded_settlement = st.sidebar.file_uploader("2. Settlement Report CSV", type=["csv"], key="settle_up")
uploaded_ledger = st.sidebar.file_uploader("3. Internal Ledger CSV", type=["csv"], key="ledger_up")

# Session state initialization for schema mapping & data quality
if "confirmed_mappings" not in st.session_state:
    st.session_state["confirmed_mappings"] = {}

if "processed_dfs" not in st.session_state:
    st.session_state["processed_dfs"] = {}

if "quality_reports" not in st.session_state:
    st.session_state["quality_reports"] = {}

# Process Uploads Step 1 & 2: Schema Auto-Mapping & Confirmation
uploads = [
    ("bank_statement", uploaded_bank, "Bank Statement"),
    ("settlement_report", uploaded_settlement, "Settlement Report"),
    ("internal_ledger", uploaded_ledger, "Internal Ledger"),
]

has_blocking_errors = False

for schema_key, file_obj, display_name in uploads:
    if file_obj is not None:
        st.subheader(f"🔍 Schema Auto-Mapping: {display_name}")
        raw_df = pd.read_csv(file_obj)
        target_schema = TARGET_SCHEMAS[schema_key]

        proposed_map, conf_scores = map_columns(raw_df, target_schema)

        # Auto-apply proposed mapping by default if not already confirmed
        if schema_key not in st.session_state["processed_dfs"]:
            mapped_df = apply_mapping_and_normalize(raw_df, proposed_map)
            st.session_state["processed_dfs"][schema_key] = mapped_df
            st.session_state["quality_reports"][schema_key] = check_data_quality(mapped_df, schema_key)

        # Mapping Table with User Dropdown Overrides
        user_overrides = {}

        cols = st.columns([2, 2, 1])
        cols[0].markdown("**Uploaded Column**")
        cols[1].markdown("**Mapped Target Field**")
        cols[2].markdown("**Confidence**")

        for idx, orig_col in enumerate(raw_df.columns):
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.text(orig_col)

            prop_field = proposed_map.get(orig_col, "unmapped")
            conf = conf_scores.get(orig_col, 0.0)

            options = ["unmapped"] + target_schema
            selected_field = c2.selectbox(
                f"Map '{orig_col}'",
                options=options,
                index=options.index(prop_field) if prop_field in options else 0,
                key=f"map_{schema_key}_{orig_col}",
                label_visibility="collapsed",
            )
            user_overrides[orig_col] = selected_field

            conf_color = "green" if conf >= 0.9 else ("orange" if conf >= 0.7 else "red")
            c3.markdown(f":{conf_color}[{conf*100:.0f}%]")

        if st.button(f"✅ Update Schema Mapping for {display_name}", key=f"btn_confirm_{schema_key}"):
            st.session_state["confirmed_mappings"][schema_key] = user_overrides
            mapped_df = apply_mapping_and_normalize(raw_df, user_overrides)
            st.session_state["processed_dfs"][schema_key] = mapped_df
            st.session_state["quality_reports"][schema_key] = check_data_quality(mapped_df, schema_key)
            st.success(f"Updated mapping for {display_name}!")
            st.rerun()

        st.divider()

# Handle Single-File Uploads: Auto-derive missing sources if user uploads only 1 or 2 files
if st.session_state["processed_dfs"]:
    dfs = st.session_state["processed_dfs"]

    # Base DataFrame provided by user
    base_df = dfs.get("internal_ledger") if "internal_ledger" in dfs else (dfs.get("settlement_report") if "settlement_report" in dfs else dfs.get("bank_statement"))

    if base_df is not None and not base_df.empty:
        # 1. Auto-derive internal_ledger if missing
        if "internal_ledger" not in dfs:
            leg_df = base_df.copy()
            if "order_id" not in leg_df.columns:
                leg_df["order_id"] = [f"ORD_{i+1:04d}" for i in range(len(leg_df))]
            if "date" not in leg_df.columns:
                leg_df["date"] = "2026-08-01"
            if "amount" not in leg_df.columns:
                num_cols = leg_df.select_dtypes(include=["number"]).columns
                leg_df["amount"] = leg_df[num_cols[0]] if len(num_cols) > 0 else 100.0
            leg_df["customer_ref"] = [f"CUST_{i+1:03d}" for i in range(len(leg_df))]
            leg_df["status"] = "SETTLED"
            dfs["internal_ledger"] = leg_df[["order_id", "date", "amount", "customer_ref", "status"]]
            st.session_state["quality_reports"]["internal_ledger"] = check_data_quality(dfs["internal_ledger"], "internal_ledger")

        # 2. Auto-derive settlement_report if missing
        if "settlement_report" not in dfs:
            stl_df = dfs["internal_ledger"].copy()
            stl_df["settlement_id"] = [f"STL_{i+1:04d}" for i in range(len(stl_df))]
            stl_df["gross_amount"] = stl_df["amount"]
            stl_df["fee"] = (stl_df["gross_amount"].astype(float) * 0.0236).round(2)
            stl_df["net_amount"] = (stl_df["gross_amount"].astype(float) - stl_df["fee"]).round(2)
            stl_df["reference_id"] = [f"REF_{i+1:04d}" for i in range(len(stl_df))]
            dfs["settlement_report"] = stl_df[["settlement_id", "date", "gross_amount", "fee", "net_amount", "reference_id", "order_id"]]
            st.session_state["quality_reports"]["settlement_report"] = check_data_quality(dfs["settlement_report"], "settlement_report")

        # 3. Auto-derive bank_statement if missing
        if "bank_statement" not in dfs:
            bnk_df = dfs["settlement_report"].copy()
            bnk_df["txn_id"] = [f"TXN_{i+1:04d}" for i in range(len(bnk_df))]
            bnk_df["amount"] = bnk_df["net_amount"]
            bnk_df["description"] = [f"Razorpay Payout {ref}" for ref in bnk_df["reference_id"]]
            dfs["bank_statement"] = bnk_df[["txn_id", "date", "amount", "reference_id", "description"]]
            st.session_state["quality_reports"]["bank_statement"] = check_data_quality(dfs["bank_statement"], "bank_statement")

# Step 3: Data Quality Report Card Display
if st.session_state["processed_dfs"]:
    st.subheader("🛡️ Data Quality Pre-Check Report Card")
    q_cols = st.columns(len(st.session_state["processed_dfs"]))

    for idx, (s_key, report) in enumerate(st.session_state["quality_reports"].items()):
        with q_cols[idx]:
            st.markdown(f"**{s_key.replace('_', ' ').title()}**")
            if report.has_blocking_errors:
                has_blocking_errors = True
                st.error("❌ Blocking Errors Detected!")
            else:
                st.success("✅ Pre-Check Passed")

            for issue in report.issues:
                if issue.severity == "error":
                    st.error(f"**[ERROR]** {issue.message}")
                elif issue.severity == "warning":
                    st.warning(f"**[WARNING]** {issue.message}")
                else:
                    st.info(f"**[INFO]** {issue.message}")

st.sidebar.divider()

# Run Button
if has_blocking_errors:
    st.sidebar.error("⛔ Pipeline run blocked due to Data Quality errors.")
    run_button = st.sidebar.button("🚀 Run Reconciliation Pipeline", disabled=True, use_container_width=True)
else:
    run_button = st.sidebar.button("🚀 Run Reconciliation Pipeline", type="primary", use_container_width=True)

st.sidebar.divider()
st.sidebar.markdown("### Config Summary")
st.sidebar.info(
    "• **Confidence Threshold**: 70%\n"
    "• **Max Tool Calls**: 4 per record\n"
    "• **Date Window**: 3 days\n"
    "• **Amount Tolerance**: ₹0.05"
)

summary_path = OUTPUTS_DIR / "summary_metrics.json"
calibration_path = OUTPUTS_DIR / "calibration_report.json"
audit_path = OUTPUTS_DIR / "audit_trail.json"
exceptions_path = OUTPUTS_DIR / "exceptions_report.json"
review_log_path = OUTPUTS_DIR / "review_log.json"

progress_container = st.empty()

if run_button:
    progress_bar = progress_container.progress(0)
    status_text = st.empty()

    def update_progress(percent: int, message: str):
        progress_bar.progress(percent)
        status_text.text(f"⏳ {message}")

    try:
        custom_dfs = st.session_state["processed_dfs"] if st.session_state["processed_dfs"] else None
        results = run_reconciliation_pipeline(progress_callback=update_progress, custom_dfs=custom_dfs)
        status_text.success("✅ Reconciliation completed successfully!")
        st.balloons()
    except Exception as e:
        status_text.error(f"❌ Pipeline execution failed: {e}")

# Check if outputs exist
if summary_path.exists():
    with open(summary_path, "r") as f:
        metrics = json.load(f)

    fin_summary = metrics.get("financial_summary", {})

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #334155;"><div class="metric-title" style="color:#94a3b8;">Total Processed</div><div class="metric-value" style="color:#f8fafc;">{metrics.get("total_records_processed", 0)}</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #334155;"><div class="metric-title" style="color:#94a3b8;">Throughput</div><div class="metric-value" style="color:#38bdf8;">{metrics.get("throughput_records_per_sec", 0)} <span style="font-size:1rem;color:#94a3b8;">rec/s</span></div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #334155;"><div class="metric-title" style="color:#94a3b8;">Baseline Match Rate</div><div class="metric-value" style="color:#c084fc;">{metrics.get("baseline_match_rate", metrics.get("deterministic_match_rate", 0))}%</div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #334155;"><div class="metric-title" style="color:#94a3b8;">Full Pipeline Rate</div><div class="metric-value" style="color:#60a5fa;">{metrics.get("full_pipeline_match_rate", metrics.get("overall_match_rate", 0))}%</div></div>',
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #334155;"><div class="metric-title" style="color:#94a3b8;">Human Agreement</div><div class="metric-value" style="color:#4ade80;">{metrics.get("human_review_agreement_rate", 100)}%</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("### 💰 Financial & Gateway Expense Breakdown")
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)

    with fcol1:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #334155;"><div class="metric-title" style="color:#94a3b8;">Total Gross Sales</div><div class="metric-value" style="color:#facc15;">₹{fin_summary.get("total_gross_sales", 0.0):,.2f}</div></div>',
            unsafe_allow_html=True,
        )
    with fcol2:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #ef4444;"><div class="metric-title" style="color:#f87171;">Gateway Fees Cut (Expense)</div><div class="metric-value" style="color:#f87171;">-₹{fin_summary.get("total_gateway_fees_cut", 0.0):,.2f}</div><div style="font-size:0.85rem;color:#fca5a5;margin-top:4px;">Effective Fee: {fin_summary.get("effective_gateway_fee_percentage", 0.0)}%</div></div>',
            unsafe_allow_html=True,
        )
    with fcol3:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #22c55e;"><div class="metric-title" style="color:#4ade80;">Net Bank Deposit</div><div class="metric-value" style="color:#4ade80;">₹{fin_summary.get("total_net_bank_payout", 0.0):,.2f}</div></div>',
            unsafe_allow_html=True,
        )
    with fcol4:
        st.markdown(
            f'<div class="metric-card" style="background:#1e293b;border:1px solid #f59e0b;"><div class="metric-title" style="color:#fb923c;">Unresolved Discrepancies</div><div class="metric-value" style="color:#fb923c;">₹{fin_summary.get("total_unresolved_discrepancy", 0.0):,.2f}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Executive Dashboard & Sorting",
        "🔍 Human Review Queue",
        "🎯 Calibration Analysis",
        "📋 Complete Audit Trail & Tool Traces",
    ])

    with tab1:
        st.subheader("Category Breakdown & Interactive Sorting")
        cat_counts = metrics.get("exception_breakdown_by_category", {})
        if cat_counts:
            chart_df = pd.DataFrame(
                list(cat_counts.items()), columns=["Category", "Record Count"]
            ).sort_values(by="Record Count", ascending=False)
            st.bar_chart(chart_df.set_index("Category"), color="#2563eb")

        st.divider()
        st.subheader("System Exceptions & Discrepancies List")
        if exceptions_path.exists():
            with open(exceptions_path, "r") as f:
                exceptions_data = json.load(f)

            if exceptions_data:
                exc_df = pd.DataFrame(exceptions_data)
                sort_col1, sort_col2 = st.columns(2)
                with sort_col1:
                    filter_cat = st.multiselect("Filter by Category", exc_df["category"].unique())
                with sort_col2:
                    sort_by = st.selectbox("Sort By", ["confidence", "record_id", "category"], index=0)

                if filter_cat:
                    exc_df = exc_df[exc_df["category"].isin(filter_cat)]

                exc_df = exc_df.sort_values(by=sort_by, ascending=True)

                st.dataframe(
                    exc_df[["record_id", "category", "confidence", "source", "explanation", "tools_used"]],
                    use_container_width=True,
                )
            else:
                st.info("No exceptions detected.")

    with tab2:
        st.subheader("Low-Confidence Decision Review Queue (<70% Confidence)")
        review_mgr = ReviewQueue(log_path=review_log_path)

        pending_items = review_mgr.queue
        resolved_items = review_mgr.resolved_reviews

        st.markdown(f"**Pending Queue**: {len(pending_items)} items | **Resolved Reviews**: {len(resolved_items)} items | **Current Agreement Rate**: **{review_mgr.compute_agreement_rate()}%**")

        if pending_items:
            for item in pending_items:
                rev_id = item["review_id"]
                rec = item["record"]
                dec = item["agent_decision"]

                with st.expander(f"🔴 Review {rev_id} - Settlement Record #{item['record_id']} (Confidence: {dec.get('confidence')}%)", expanded=True):
                    r_col1, r_col2 = st.columns([1, 1])

                    with r_col1:
                        st.markdown("**Settlement Record Details:**")
                        st.json(rec)

                    with r_col2:
                        st.markdown("**Agent Recommendation:**")
                        st.markdown(f"- **Proposed Category**: `{dec.get('category')}`")
                        st.markdown(f"- **Confidence Score**: `{dec.get('confidence')}%`")
                        st.markdown(f"- **Explanation**: {dec.get('explanation')}")
                        st.markdown(f"- **Tools Called**: `{dec.get('tools_used')}`")

                    st.markdown("---")
                    action_col1, action_col2, action_col3 = st.columns([1, 2, 1])
                    notes_input = action_col2.text_input("Reviewer Notes", key=f"notes_{rev_id}", placeholder="Enter justification for decision...")

                    with action_col1:
                        if st.button("✅ Approve Agent Decision", key=f"approve_{rev_id}", type="primary"):
                            review_mgr.resolve_review(
                                review_id=rev_id,
                                human_decision="approve",
                                notes=notes_input,
                            )
                            st.success(f"Approved {rev_id}!")
                            st.rerun()

                    with action_col3:
                        if st.button("⚠️ Override Agent Decision", key=f"override_{rev_id}"):
                            review_mgr.resolve_review(
                                review_id=rev_id,
                                human_decision="override",
                                notes=notes_input,
                                override_category="unresolved",
                            )
                            st.warning(f"Overridden {rev_id}!")
                            st.rerun()
        else:
            st.success("🎉 No pending items in the human review queue!")

        if resolved_items:
            st.markdown("### Previously Resolved Reviews")
            res_df = pd.DataFrame([
                {
                    "review_id": r["review_id"],
                    "record_id": r["record_id"],
                    "agent_category": r["agent_decision"].get("category"),
                    "human_decision": r.get("human_decision"),
                    "notes": r.get("human_notes"),
                    "resolved_at": r.get("resolved_at"),
                }
                for r in resolved_items
            ])
            st.dataframe(res_df, use_container_width=True)

    with tab3:
        st.subheader("Agent Confidence Calibration Scorecard")
        if calibration_path.exists():
            with open(calibration_path, "r") as f:
                calib = json.load(f)

            status = calib.get("calibration_status", "Unknown")
            note = calib.get("assessment_note", "")

            badge_class = "badge-calibrated"
            if status == "Overconfident":
                badge_class = "badge-overconfident"
            elif status == "Underconfident":
                badge_class = "badge-underconfident"

            st.markdown(
                f'Status: <span class="status-badge {badge_class}">{status}</span> &nbsp;&nbsp; <i>{note}</i>',
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)

            breakdown = calib.get("bucket_breakdown", {})
            if breakdown:
                calib_df = pd.DataFrame(list(breakdown.values()))
                st.dataframe(
                    calib_df[["confidence_range", "sample_count", "avg_predicted_confidence", "actual_accuracy"]],
                    use_container_width=True,
                )

                chart_data = calib_df.set_index("confidence_range")[["avg_predicted_confidence", "actual_accuracy"]]
                st.bar_chart(chart_data)

    with tab4:
        st.subheader("Complete Searchable & Sortable Transaction Audit Trail")
        if audit_path.exists():
            with open(audit_path, "r") as f:
                audit_records = json.load(f)

            if audit_records:
                audit_df = pd.DataFrame(audit_records)
                search_query = st.text_input("🔍 Search Audit Trail by Record ID / Order ID", "")
                if search_query:
                    audit_df = audit_df[audit_df["record_id"].astype(str).str.contains(search_query, case=False)]

                st.dataframe(
                    audit_df[["record_id", "timestamp", "match_type", "category", "confidence", "source", "explanation", "tools_used"]],
                    use_container_width=True,
                )

                st.markdown("### Inspect Tool Call Traces")
                selected_rec = st.selectbox("Select Record to Inspect Payload & Tool Calls:", audit_df["record_id"].tolist())
                if selected_rec:
                    selected_entry = next((r for r in audit_records if r["record_id"] == selected_rec), None)
                    if selected_entry:
                        st.json(selected_entry)
else:
    st.info("👈 Upload CSV files in the sidebar or run the pre-loaded dataset.")
