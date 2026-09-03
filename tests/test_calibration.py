"""Unit tests for calibration accuracy analysis module."""

import json
import sys
from pathlib import Path
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration import evaluate_calibration


def test_calibration_evaluation(tmp_path: Path):
    """Test confidence bucket accuracy calculation against a mock ground truth file."""
    ground_truth = {
        "REF1001": {"expected_match": True, "true_category": "exact_match"},
        "REF1002": {"expected_match": True, "true_category": "fee_adjustment"},
        "REF1003": {"expected_match": False, "true_category": "unresolved"},
    }

    gt_path = tmp_path / "ground_truth.json"
    report_path = tmp_path / "calibration_report.json"

    with open(gt_path, "w") as f:
        json.dump(ground_truth, f)

    agent_decisions = [
        {
            "record_id": "REF1001",
            "confidence": 95.0,
            "is_match": True,
            "category": "exact_match",
        },
        {
            "record_id": "REF1002",
            "confidence": 85.0,
            "is_match": True,
            "category": "fee_adjustment",
        },
        {
            "record_id": "REF1003",
            "confidence": 40.0,
            "is_match": False,
            "category": "unresolved",
        },
    ]

    report = evaluate_calibration(
        agent_decisions=agent_decisions,
        ground_truth_path=gt_path,
        output_path=report_path,
    )

    assert "calibration_status" in report
    assert report["overall_metrics"]["total_records_evaluated"] == 3
    assert report["overall_metrics"]["overall_actual_accuracy"] == 100.0

    breakdown = report["bucket_breakdown"]
    assert "90-100" in breakdown
    assert breakdown["90-100"]["sample_count"] == 1
    assert breakdown["90-100"]["actual_accuracy"] == 100.0
