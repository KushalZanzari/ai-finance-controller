"""Data Quality Pre-Check engine for inspecting DataFrames before pipeline execution."""

from dataclasses import dataclass, field
from typing import Any
import pandas as pd
from dateutil import parser as date_parser

from src.logging_config import logger


@dataclass
class QualityIssue:
    """Represents a single data quality issue discovered in an uploaded dataset."""
    issue_type: str
    severity: str  # 'info', 'warning', 'error'
    column: str
    affected_rows: int
    message: str


@dataclass
class DataQualityReport:
    """Structured pre-check quality report for an uploaded dataset."""
    total_rows: int
    issues: list[QualityIssue] = field(default_factory=list)
    has_blocking_errors: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Converts report to dictionary representation."""
        return {
            "total_rows": self.total_rows,
            "has_blocking_errors": self.has_blocking_errors,
            "issues": [
                {
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "column": i.column,
                    "affected_rows": i.affected_rows,
                    "message": i.message,
                }
                for i in self.issues
            ],
        }


MANDATORY_COLUMNS = {
    "bank_statement": ["date", "amount", "reference_id"],
    "settlement_report": ["settlement_id", "date", "gross_amount", "net_amount", "reference_id"],
    "internal_ledger": ["order_id", "date", "amount"],
}


def check_data_quality(df: pd.DataFrame, dataset_type: str = "bank_statement") -> DataQualityReport:
    """Scans a mapped DataFrame for data quality issues without mutating the underlying data.

    Args:
        df (pd.DataFrame): Mapped input DataFrame to inspect.
        dataset_type (str): Type of dataset ('bank_statement', 'settlement_report', 'internal_ledger').

    Returns:
        DataQualityReport: Comprehensive data quality report.
    """
    total_rows = len(df)
    report = DataQualityReport(total_rows=total_rows)

    if df.empty or total_rows == 0:
        report.issues.append(
            QualityIssue(
                issue_type="empty_file",
                severity="error",
                column="all",
                affected_rows=0,
                message="Uploaded file contains no rows or records.",
            )
        )
        report.has_blocking_errors = True
        return report

    # -------------------------------------------------------------------------
    # 1. Missing Critical Columns Check (ERROR severity)
    # -------------------------------------------------------------------------
    mandatory = MANDATORY_COLUMNS.get(dataset_type, ["amount", "date"])
    missing_critical = [col for col in mandatory if col not in df.columns]

    if missing_critical:
        report.issues.append(
            QualityIssue(
                issue_type="missing_critical_columns",
                severity="error",
                column=", ".join(missing_critical),
                affected_rows=total_rows,
                message=f"Dataset is missing critical matching column(s): {', '.join(missing_critical)}. Matching cannot proceed.",
            )
        )
        report.has_blocking_errors = True

    # -------------------------------------------------------------------------
    # 2. Missing/Null Values per Column
    # -------------------------------------------------------------------------
    for col in df.columns:
        null_cnt = int(df[col].isna().sum())
        if null_cnt > 0:
            severity = "error" if col in mandatory and null_cnt == total_rows else "warning"
            if severity == "error":
                report.has_blocking_errors = True

            report.issues.append(
                QualityIssue(
                    issue_type="null_values",
                    severity=severity,
                    column=str(col),
                    affected_rows=null_cnt,
                    message=f"Column '{col}' has {null_cnt} missing/null values ({null_cnt / total_rows * 100:.1f}%).",
                )
            )

    # -------------------------------------------------------------------------
    # 3. Duplicate Rows & Specific Key Duplicates
    # -------------------------------------------------------------------------
    full_dups = int(df.duplicated().sum())
    if full_dups > 0:
        report.issues.append(
            QualityIssue(
                issue_type="full_duplicate_rows",
                severity="warning",
                column="all",
                affected_rows=full_dups,
                message=f"Dataset contains {full_dups} identical duplicate rows.",
            )
        )

    for key_col in ["reference_id", "order_id", "settlement_id"]:
        if key_col in df.columns:
            key_dups = int(df.duplicated(subset=[key_col]).sum())
            if key_dups > 0:
                report.issues.append(
                    QualityIssue(
                        issue_type="duplicate_reference_key",
                        severity="warning",
                        column=key_col,
                        affected_rows=key_dups,
                        message=f"Column '{key_col}' has {key_dups} duplicate values (reused IDs).",
                    )
                )

    # -------------------------------------------------------------------------
    # 4. Non-Numeric or Negative Amount Values
    # -------------------------------------------------------------------------
    amount_cols = [c for c in df.columns if any(a_kw in c for a_kw in ["amount", "gross", "fee", "net", "price"])]
    for amt_col in amount_cols:
        # Check non-numeric
        non_numeric_cnt = 0
        neg_cnt = 0
        for val in df[amt_col]:
            if pd.isna(val):
                continue
            try:
                f_val = float(val)
                if f_val < 0 and amt_col != "fee":
                    neg_cnt += 1
            except (ValueError, TypeError):
                non_numeric_cnt += 1

        if non_numeric_cnt > 0:
            report.issues.append(
                QualityIssue(
                    issue_type="non_numeric_amount",
                    severity="error",
                    column=amt_col,
                    affected_rows=non_numeric_cnt,
                    message=f"Amount column '{amt_col}' contains {non_numeric_cnt} non-numeric string values.",
                )
            )
            report.has_blocking_errors = True

        if neg_cnt > 0:
            report.issues.append(
                QualityIssue(
                    issue_type="negative_amount",
                    severity="warning",
                    column=amt_col,
                    affected_rows=neg_cnt,
                    message=f"Amount column '{amt_col}' contains {neg_cnt} negative values.",
                )
            )

    # -------------------------------------------------------------------------
    # 5. Malformed Date Inspection
    # -------------------------------------------------------------------------
    if "date" in df.columns:
        malformed_dates = 0
        for d_val in df["date"]:
            if pd.isna(d_val) or not d_val:
                malformed_dates += 1
                continue
            try:
                date_parser.parse(str(d_val))
            except Exception:
                malformed_dates += 1

        if malformed_dates > 0:
            severity = "error" if malformed_dates == total_rows else "warning"
            if severity == "error":
                report.has_blocking_errors = True

            report.issues.append(
                QualityIssue(
                    issue_type="malformed_dates",
                    severity=severity,
                    column="date",
                    affected_rows=malformed_dates,
                    message=f"Date column contains {malformed_dates} malformed or unparseable date values.",
                )
            )

    # -------------------------------------------------------------------------
    # 6. All-Empty Critical Fields Check
    # -------------------------------------------------------------------------
    present_critical = [c for c in mandatory if c in df.columns]
    if present_critical:
        empty_critical = int(df[present_critical].isna().all(axis=1).sum())
        if empty_critical > 0:
            report.issues.append(
                QualityIssue(
                    issue_type="empty_critical_fields",
                    severity="warning",
                    column=", ".join(present_critical),
                    affected_rows=empty_critical,
                    message=f"Found {empty_critical} rows where all critical matching fields are completely blank.",
                )
            )

    logger.info(f"Data quality pre-check complete for {dataset_type}: {len(report.issues)} issues found. Blocking: {report.has_blocking_errors}")
    return report
