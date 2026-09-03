"""Report generation module for summary metrics and detailed exception reports."""

import json
from pathlib import Path
from typing import Any

from config.settings import OUTPUTS_DIR
from src.logging_config import logger

SUMMARY_METRICS_PATH = OUTPUTS_DIR / "summary_metrics.json"
EXCEPTIONS_REPORT_PATH = OUTPUTS_DIR / "exceptions_report.json"


def generate_reports(
    total_records: int,
    elapsed_seconds: float,
    deterministic_matches_count: int,
    agent_matches_count: int,
    audit_records: list[dict[str, Any]],
    human_agreement_rate: float,
    calibration_summary: str,
    output_dir: Path = OUTPUTS_DIR,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Generates summary_metrics.json and exceptions_report.json.

    Args:
        total_records (int): Total settlement records processed.
        elapsed_seconds (float): Total pipeline processing duration.
        deterministic_matches_count (int): Count of records resolved deterministically.
        agent_matches_count (int): Count of records resolved via agent.
        audit_records (list[dict[str, Any]]): Full audit trail records.
        human_agreement_rate (float): Calculated human agreement percentage.
        calibration_summary (str): Calibration assessment string ('Well-Calibrated', etc.).
        output_dir (Path): Output directory path.

    Returns:
        tuple[dict[str, Any], list[dict[str, Any]]]: Summary metrics dict and exceptions list.
    """
    throughput = round(total_records / elapsed_seconds, 2) if elapsed_seconds > 0 else 0.0

    total_resolved = deterministic_matches_count + agent_matches_count
    overall_match_rate = round((total_resolved / total_records) * 100.0, 2) if total_records > 0 else 0.0
    det_match_rate = round((deterministic_matches_count / total_records) * 100.0, 2) if total_records > 0 else 0.0
    agent_match_rate = round((agent_matches_count / total_records) * 100.0, 2) if total_records > 0 else 0.0

    # Exception Breakdown by Taxonomy Category
    category_counts: dict[str, int] = {}
    exceptions_list: list[dict[str, Any]] = []

    total_gross_amount = 0.0
    total_fees_cut = 0.0
    total_net_payout = 0.0
    total_unresolved_amount = 0.0

    for entry in audit_records:
        cat = entry.get("category", "unresolved")
        category_counts[cat] = category_counts.get(cat, 0) + 1

        details = entry.get("details", {})
        stl = details.get("settlement") or details.get("candidate_settlement") or {}

        gross = float(stl.get("gross_amount", 0.0))
        fee = float(stl.get("fee", 0.0))
        net = float(stl.get("net_amount", 0.0))

        total_gross_amount += gross
        total_fees_cut += fee
        total_net_payout += net

        if cat == "unresolved":
            total_unresolved_amount += net if net > 0 else gross

        # Collect every unresolved, non-exact, or human-reviewed record into exceptions report
        if entry.get("category") != "exact_match" or entry.get("source") == "human_reviewed" or entry.get("confidence", 100) < 100:
            exceptions_list.append({
                "record_id": entry.get("record_id"),
                "category": cat,
                "confidence": entry.get("confidence"),
                "source": entry.get("source"),
                "explanation": entry.get("explanation"),
                "tools_used": entry.get("tools_used", []),
                "timestamp": entry.get("timestamp"),
            })

    effective_fee_pct = round((total_fees_cut / total_gross_amount) * 100.0, 2) if total_gross_amount > 0 else 0.0

    summary_metrics = {
        "pipeline_execution_seconds": round(elapsed_seconds, 4),
        "total_records_processed": total_records,
        "throughput_records_per_sec": throughput,
        "deterministic_matches_count": deterministic_matches_count,
        "agent_matches_count": agent_matches_count,
        "baseline_match_rate": det_match_rate,
        "full_pipeline_match_rate": overall_match_rate,
        "deterministic_match_rate": det_match_rate,
        "agent_assisted_match_rate": agent_match_rate,
        "overall_match_rate": overall_match_rate,
        "human_review_agreement_rate": human_agreement_rate,
        "calibration_summary": calibration_summary,
        "financial_summary": {
            "total_gross_sales": round(total_gross_amount, 2),
            "total_gateway_fees_cut": round(total_fees_cut, 2),
            "total_net_bank_payout": round(total_net_payout, 2),
            "total_unresolved_discrepancy": round(total_unresolved_amount, 2),
            "effective_gateway_fee_percentage": effective_fee_pct,
        },
        "exception_breakdown_by_category": category_counts,
    }

    output_dir.mkdir(exist_ok=True, parents=True)

    with open(output_dir / "summary_metrics.json", "w") as f:
        json.dump(summary_metrics, f, indent=2)

    with open(output_dir / "exceptions_report.json", "w") as f:
        json.dump(exceptions_list, f, indent=2)

    logger.info(f"Generated summary metrics (Throughput: {throughput} rec/s, Overall Match Rate: {overall_match_rate}%)")
    logger.info(f"Generated exceptions report with {len(exceptions_list)} entries.")

    return summary_metrics, exceptions_list
