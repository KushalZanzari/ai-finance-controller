"""Main pipeline orchestrator for AI Finance Controller reconciliation workflow.

Executes deterministic matching, agent reasoning, human review routing, calibration,
and audit logging in sequence.
"""

import sys
import time
from pathlib import Path
from typing import Any

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from config.settings import DATA_DIR, OUTPUTS_DIR
from src.audit import AuditLogger
from src.calibration import evaluate_calibration
from src.llm_agent import ReActReasoningAgent
from src.logging_config import logger
from src.matcher import DeterministicMatcher
from src.report import generate_reports
from src.review import ReviewQueue


def run_reconciliation_pipeline(
    data_dir: Path = DATA_DIR,
    outputs_dir: Path = OUTPUTS_DIR,
    progress_callback: Any = None,
    custom_dfs: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Runs the end-to-end reconciliation pipeline.

    Args:
        data_dir (Path): Path to directory containing bank_statement.csv, settlement_report.csv, internal_ledger.csv.
        outputs_dir (Path): Output directory for JSON reports.
        progress_callback (Callable | None): Optional callback function for UI progress updates.
        custom_dfs (dict[str, pd.DataFrame] | None): Optional dictionary of pre-mapped & normalized DataFrames.

    Returns:
        dict[str, Any]: Execution results containing summary metrics, audit trail, calibration report, and exceptions.
    """
    start_time = time.time()
    logger.info("=========================================================")
    logger.info("Starting AI Finance Controller Reconciliation Pipeline")
    logger.info("=========================================================")

    if progress_callback:
        progress_callback(10, "Loading financial datasets...")

    # Load CSV data or use provided custom DataFrames
    if custom_dfs and "bank_statement" in custom_dfs and "settlement_report" in custom_dfs and "internal_ledger" in custom_dfs:
        bank_df = custom_dfs["bank_statement"]
        settlement_df = custom_dfs["settlement_report"]
        ledger_df = custom_dfs["internal_ledger"]
    else:
        bank_path = data_dir / "bank_statement.csv"
        settlement_path = data_dir / "settlement_report.csv"
        ledger_path = data_dir / "internal_ledger.csv"

        if not (bank_path.exists() and settlement_path.exists() and ledger_path.exists()):
            raise FileNotFoundError(f"Missing required CSV files in {data_dir}. Run data/generate_synthetic_data.py first.")

        bank_df = pd.read_csv(bank_path)
        settlement_df = pd.read_csv(settlement_path)
        ledger_df = pd.read_csv(ledger_path)

    audit = AuditLogger(outputs_dir / "audit_trail.json")
    review_queue = ReviewQueue(log_path=outputs_dir / "review_log.json")
    agent = ReActReasoningAgent()

    # -------------------------------------------------------------------------
    # Stage 1: Deterministic Pass (Exact + Bounded Subset-Sum Many-to-One)
    # -------------------------------------------------------------------------
    if progress_callback:
        progress_callback(30, "Executing Stage 1: Deterministic & Subset-Sum Matcher...")

    matcher = DeterministicMatcher()
    det_matches, ambiguous_candidates, det_elapsed, total_records = matcher.run_deterministic_pass(
        bank_df=bank_df,
        settlement_df=settlement_df,
        ledger_df=ledger_df,
    )

    # Log deterministic matches to audit trail
    for match in det_matches:
        audit.log_record(
            record_id=match.settlement_id,
            match_type=match.match_type,
            category=match.category,
            confidence=match.confidence * 100.0,
            source="deterministic",
            explanation=match.explanation,
            tools_used=[],
            details=match.details,
        )

    # -------------------------------------------------------------------------
    # Stage 2 & 3: ReAct LLM Agent Reasoning & Human Review Queue Routing
    # -------------------------------------------------------------------------
    if progress_callback:
        progress_callback(60, f"Executing Stage 2: ReAct Agent Loop for {len(ambiguous_candidates)} candidates...")

    agent_decisions = []
    agent_match_count = 0

    for idx, candidate in enumerate(ambiguous_candidates):
        stl_id = str(candidate.settlement_record.get("settlement_id"))
        ref_id = str(candidate.settlement_record.get("reference_id"))

        decision = agent.analyze_candidate_pair(candidate)
        decision["record_id"] = stl_id or ref_id
        decision["details"] = {"candidate_settlement": candidate.settlement_record}
        agent_decisions.append(decision)

        conf = decision.get("confidence", 0.0)

        # Route low confidence (<70) decisions to human review queue
        if review_queue.should_route_to_review(conf):
            review_queue.add_to_review_queue(candidate.settlement_record, decision)
            source = "human_reviewed"
        else:
            source = "agent_auto"
            if decision.get("is_match"):
                agent_match_count += 1

        audit.log_record(
            record_id=stl_id or ref_id,
            match_type="agent_assisted",
            category=decision.get("category", "unresolved"),
            confidence=conf,
            source=source,
            explanation=decision.get("explanation", ""),
            tools_used=decision.get("tools_used", []),
            details={"candidate_settlement": candidate.settlement_record},
        )

    # -------------------------------------------------------------------------
    # Stage 4: Calibration Evaluation against Ground Truth
    # -------------------------------------------------------------------------
    if progress_callback:
        progress_callback(85, "Executing Stage 3: Calibration & Accuracy Analysis...")

    calibration_report = evaluate_calibration(
        agent_decisions=agent_decisions,
        ground_truth_path=data_dir / "ground_truth.json",
        output_path=outputs_dir / "calibration_report.json",
    )

    # -------------------------------------------------------------------------
    # Stage 5: Summary Reporting & Audit Export
    # -------------------------------------------------------------------------
    if progress_callback:
        progress_callback(95, "Generating final summary metrics & exception reports...")

    audit.save()

    total_pipeline_time = time.time() - start_time
    agreement_rate = review_queue.compute_agreement_rate()

    summary_metrics, exceptions_list = generate_reports(
        total_records=total_records,
        elapsed_seconds=total_pipeline_time,
        deterministic_matches_count=len(det_matches),
        agent_matches_count=agent_match_count,
        audit_records=audit.records,
        human_agreement_rate=agreement_rate,
        calibration_summary=calibration_report.get("calibration_status", "Unknown"),
        output_dir=outputs_dir,
    )

    if progress_callback:
        progress_callback(100, "Reconciliation pipeline completed successfully!")

    logger.info("=========================================================")
    logger.info(f"Pipeline Complete in {total_pipeline_time:.2f}s | Throughput: {summary_metrics['throughput_records_per_sec']} rec/s")
    logger.info(f"Deterministic Match Rate: {summary_metrics['deterministic_match_rate']}% | Overall Match Rate: {summary_metrics['overall_match_rate']}%")
    logger.info("=========================================================")

    return {
        "summary_metrics": summary_metrics,
        "calibration_report": calibration_report,
        "audit_trail": audit.records,
        "exceptions_report": exceptions_list,
        "review_queue": review_queue,
    }


if __name__ == "__main__":
    run_reconciliation_pipeline()
