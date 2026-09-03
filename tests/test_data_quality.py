"""Unit tests for data quality pre-check engine."""

import sys
from pathlib import Path
import pandas as pd
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_quality import check_data_quality


def test_data_quality_missing_critical_column():
    """Test blocking error detection when critical matching columns are missing."""
    invalid_df = pd.DataFrame({
        "random_header": [1, 2, 3],
        "some_text": ["A", "B", "C"],
    })

    report = check_data_quality(invalid_df, dataset_type="bank_statement")

    assert report.has_blocking_errors is True
    error_issues = [i for i in report.issues if i.severity == "error"]
    assert len(error_issues) > 0
    assert "missing_critical_columns" in [i.issue_type for i in error_issues]


def test_data_quality_nulls_and_duplicates():
    """Test detection of null values and duplicate reference IDs."""
    valid_df = pd.DataFrame({
        "date": ["2026-08-01", "2026-08-02", None],
        "amount": [100.0, 200.0, 300.0],
        "reference_id": ["REF100", "REF100", "REF102"],  # Duplicate REF100
        "txn_id": ["TXN1", "TXN2", "TXN3"],
        "description": ["D1", "D2", "D3"],
    })

    report = check_data_quality(valid_df, dataset_type="bank_statement")

    assert report.has_blocking_errors is False  # Warnings exist but non-blocking
    dup_issues = [i for i in report.issues if i.issue_type == "duplicate_reference_key"]
    assert len(dup_issues) == 1
    assert dup_issues[0].affected_rows == 1

    null_issues = [i for i in report.issues if i.issue_type == "null_values"]
    assert len(null_issues) == 1
    assert null_issues[0].column == "date"
