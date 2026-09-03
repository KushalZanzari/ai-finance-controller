"""Calibration analysis comparing agent confidence scores to ground truth accuracy."""

import json
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR, OUTPUTS_DIR
from src.logging_config import logger

CALIBRATION_REPORT_PATH = OUTPUTS_DIR / "calibration_report.json"
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"


def evaluate_calibration(
    agent_decisions: list[dict[str, Any]],
    ground_truth_path: Path = GROUND_TRUTH_PATH,
    output_path: Path = CALIBRATION_REPORT_PATH,
) -> dict[str, Any]:
    """Buckets agent decisions by confidence and computes actual accuracy against hidden ground truth.

    Args:
        agent_decisions (list[dict[str, Any]]): List of agent decision dicts containing 'record_id', 'confidence', 'category', 'is_match'.
        ground_truth_path (Path): Path to hidden ground truth JSON file.
        output_path (Path): Path to output calibration_report.json file.

    Returns:
        dict[str, Any]: Detailed calibration analysis report.
    """
    ground_truth = {}
    if ground_truth_path.exists():
        with open(ground_truth_path, "r") as f:
            ground_truth = json.load(f)
    else:
        logger.warning(f"Ground truth file not found at {ground_truth_path}. Calibration evaluation skipped.")

    # Define confidence buckets
    buckets = {
        "0-50": {"min": 0.0, "max": 50.0, "predictions": []},
        "50-70": {"min": 50.0, "max": 70.0, "predictions": []},
        "70-90": {"min": 70.0, "max": 90.0, "predictions": []},
        "90-100": {"min": 90.0, "max": 100.0, "predictions": []},
    }

    total_evaluated = 0
    total_correct = 0

    for dec in agent_decisions:
        rec_id = str(dec.get("record_id", ""))
        ref_id = str(dec.get("details", {}).get("candidate_settlement", {}).get("reference_id", ""))
        conf = float(dec.get("confidence", 0.0))

        # Lookup ground truth using rec_id or ref_id or substring matching
        truth_entry = ground_truth.get(rec_id) or ground_truth.get(ref_id)
        if not truth_entry:
            # Try fuzzy lookup in ground truth keys
            matched_key = next(
                (k for k in ground_truth if (rec_id and rec_id in k) or (ref_id and ref_id in k) or (k in rec_id) or (k in ref_id)),
                None
            )
            if matched_key:
                truth_entry = ground_truth[matched_key]

        is_correct = False
        if truth_entry:
            expected_match = truth_entry.get("expected_match", True)
            expected_cat = truth_entry.get("true_category", "")
            agent_is_match = dec.get("is_match", True)
            agent_cat = dec.get("category", "")

            # Match is correct if match status aligns or category aligns
            is_correct = (agent_is_match == expected_match) and (
                agent_cat == expected_cat or agent_is_match is True
            )

        item = {
            "record_id": rec_id,
            "confidence": conf,
            "agent_category": dec.get("category"),
            "true_category": truth_entry.get("true_category") if truth_entry else "unknown",
            "is_correct": is_correct,
        }

        total_evaluated += 1
        if is_correct:
            total_correct += 1

        # Place into appropriate bucket
        for bucket_name, b_data in buckets.items():
            if (b_data["min"] <= conf < b_data["max"]) or (bucket_name == "90-100" and conf == 100.0):
                b_data["predictions"].append(item)
                break

    # Summarize per-bucket accuracy
    bucket_summary = {}
    total_conf_sum = 0.0

    for b_name, b_data in buckets.items():
        preds = b_data["predictions"]
        count = len(preds)
        if count > 0:
            avg_conf = round(sum(p["confidence"] for p in preds) / count, 2)
            correct_cnt = sum(1 for p in preds if p["is_correct"])
            accuracy = round((correct_cnt / count) * 100.0, 2)
            total_conf_sum += sum(p["confidence"] for p in preds)
        else:
            avg_conf = 0.0
            accuracy = 0.0
            correct_cnt = 0

        bucket_summary[b_name] = {
            "confidence_range": b_name,
            "sample_count": count,
            "avg_predicted_confidence": avg_conf,
            "correct_count": correct_cnt,
            "actual_accuracy": accuracy,
        }

    overall_avg_predicted = round(total_conf_sum / total_evaluated, 2) if total_evaluated > 0 else 0.0
    overall_accuracy = round((total_correct / total_evaluated) * 100.0, 2) if total_evaluated > 0 else 0.0

    # Determine calibration assessment
    conf_diff = overall_avg_predicted - overall_accuracy
    if abs(conf_diff) <= 10.0:
        calibration_status = "Well-Calibrated"
        assessment_note = f"Agent confidence ({overall_avg_predicted}%) aligns closely with empirical accuracy ({overall_accuracy}%)."
    elif conf_diff > 10.0:
        calibration_status = "Overconfident"
        assessment_note = f"Agent predicted higher confidence ({overall_avg_predicted}%) than empirical accuracy achieved ({overall_accuracy}%)."
    else:
        calibration_status = "Underconfident"
        assessment_note = f"Agent empirical accuracy ({overall_accuracy}%) exceeded self-reported confidence ({overall_avg_predicted}%)."

    report = {
        "calibration_status": calibration_status,
        "assessment_note": assessment_note,
        "overall_metrics": {
            "total_records_evaluated": total_evaluated,
            "overall_avg_predicted_confidence": overall_avg_predicted,
            "overall_actual_accuracy": overall_accuracy,
        },
        "bucket_breakdown": bucket_summary,
    }

    output_path.parent.mkdir(exist_ok=True, parents=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Calibration analysis complete. Status: {calibration_status} (Accuracy: {overall_accuracy}%, Avg Conf: {overall_avg_predicted}%)")
    return report
