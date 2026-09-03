"""Audit trail logger and reporter.

Maintains complete, inspectable audit records for every processed transaction.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import OUTPUTS_DIR
from src.logging_config import logger

AUDIT_TRAIL_PATH = OUTPUTS_DIR / "audit_trail.json"


class AuditLogger:
    """Manager for appending and persisting transaction audit records."""

    def __init__(self, output_path: Path = AUDIT_TRAIL_PATH) -> None:
        """Initializes the audit logger.

        Args:
            output_path (Path): Path to audit_trail.json output file.
        """
        self.output_path = output_path
        self.records: list[dict[str, Any]] = []

    def log_record(
        self,
        record_id: str,
        match_type: str,
        category: str,
        confidence: float,
        source: str,  # 'deterministic', 'agent_auto', 'human_reviewed'
        explanation: str,
        tools_used: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Logs an audit entry for a resolved transaction.

        Args:
            record_id (str): Primary identifier (settlement_id or reference_id).
            match_type (str): Match type identifier (exact, many_to_one, agent, etc.).
            category (str): Taxonomy classification category.
            confidence (float): Confidence score (0-100).
            source (str): Source of resolution ('deterministic', 'agent_auto', 'human_reviewed').
            explanation (str): Human-readable decision justification.
            tools_used (list[str] | None): Tools invoked during agent reasoning.
            details (dict[str, Any] | None): Supplementary payload details.

        Returns:
            dict[str, Any]: Formatted audit trail entry.
        """
        entry = {
            "record_id": record_id,
            "timestamp": datetime.utcnow().isoformat(),
            "match_type": match_type,
            "category": category,
            "confidence": round(float(confidence), 2),
            "source": source,
            "explanation": explanation,
            "tools_used": tools_used or [],
            "details": details or {},
        }

        self.records.append(entry)
        return entry

    def save(self) -> None:
        """Saves all logged audit entries to disk."""
        self.output_path.parent.mkdir(exist_ok=True, parents=True)
        with open(self.output_path, "w") as f:
            json.dump(self.records, f, indent=2)

        logger.info(f"Saved {len(self.records)} audit entries to {self.output_path}")
