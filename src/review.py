"""Human review queue management and agreement rate tracking.

Routes low-confidence decisions to a review queue and tracks human approval vs. override rate.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import CONFIDENCE_THRESHOLD, OUTPUTS_DIR
from src.logging_config import logger

REVIEW_LOG_PATH = OUTPUTS_DIR / "review_log.json"


class ReviewQueue:
    """Manager for the human-in-the-loop review queue."""

    def __init__(
        self,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        log_path: Path = REVIEW_LOG_PATH,
    ) -> None:
        """Initializes the review queue manager.

        Args:
            confidence_threshold (float): Threshold below which records enter review (default 70).
            log_path (Path): Path to review_log.json file.
        """
        self.confidence_threshold = confidence_threshold
        self.log_path = log_path
        self.queue: list[dict[str, Any]] = []
        self.resolved_reviews: list[dict[str, Any]] = []
        self.load_log()

    def load_log(self) -> None:
        """Loads existing review logs from disk if available."""
        if self.log_path.exists():
            try:
                with open(self.log_path, "r") as f:
                    data = json.load(f)
                    self.queue = data.get("pending_queue", [])
                    self.resolved_reviews = data.get("resolved_reviews", [])
            except Exception as e:
                logger.warning(f"Could not load review log from {self.log_path}: {e}")

    def save_log(self) -> None:
        """Persists queue and resolved reviews to review_log.json."""
        data = {
            "pending_queue": self.queue,
            "resolved_reviews": self.resolved_reviews,
            "agreement_rate": self.compute_agreement_rate(),
            "last_updated": datetime.utcnow().isoformat(),
        }
        with open(self.log_path, "w") as f:
            json.dump(data, f, indent=2)

    def should_route_to_review(self, confidence: float) -> bool:
        """Determines if a record should be routed to human review based on confidence.

        Args:
            confidence (float): Self-reported agent confidence (0-100).

        Returns:
            bool: True if confidence < threshold.
        """
        return confidence < self.confidence_threshold

    def add_to_review_queue(self, record: dict[str, Any], agent_decision: dict[str, Any]) -> str:
        """Enqueues a low-confidence decision for human review.

        Args:
            record (dict[str, Any]): Record metadata/settlement info.
            agent_decision (dict[str, Any]): Agent's proposed decision output.

        Returns:
            str: Unique review ID.
        """
        review_id = f"REV_{len(self.queue) + len(self.resolved_reviews) + 1:03d}"
        item = {
            "review_id": review_id,
            "record_id": str(record.get("settlement_id") or record.get("reference_id")),
            "record": record,
            "agent_decision": agent_decision,
            "status": "pending",
            "enqueued_at": datetime.utcnow().isoformat(),
        }
        self.queue.append(item)
        self.save_log()
        logger.info(f"Enqueued record {item['record_id']} (confidence: {agent_decision.get('confidence')}%) into human review queue.")
        return review_id

    def resolve_review(
        self,
        review_id: str,
        human_decision: str,
        notes: str = "",
        override_category: str | None = None,
    ) -> dict[str, Any]:
        """Resolves a pending review item with human approval or override.

        Args:
            review_id (str): ID of the review item.
            human_decision (str): 'approve' or 'override'.
            notes (str): Reviewer justification notes.
            override_category (str | None): Corrected category if overridden.

        Returns:
            dict[str, Any]: Resolved review entry.
        """
        item_idx = next((i for i, item in enumerate(self.queue) if item["review_id"] == review_id), None)
        if item_idx is None:
            raise ValueError(f"Review ID {review_id} not found in pending queue.")

        item = self.queue.pop(item_idx)
        item["status"] = "resolved"
        item["human_decision"] = human_decision.lower()  # 'approve' or 'override'
        item["human_notes"] = notes
        item["override_category"] = override_category or item["agent_decision"].get("category")
        item["resolved_at"] = datetime.utcnow().isoformat()

        self.resolved_reviews.append(item)
        self.save_log()
        logger.info(f"Resolved review {review_id}: {human_decision.upper()}")
        return item

    def compute_agreement_rate(self) -> float:
        """Computes human agreement rate (% of agent decisions approved without override).

        Returns:
            float: Agreement rate percentage (0.0 to 100.0). Returns 100.0 if no reviews completed yet.
        """
        if not self.resolved_reviews:
            return 100.0

        approvals = sum(1 for r in self.resolved_reviews if r.get("human_decision") == "approve")
        rate = round((approvals / len(self.resolved_reviews)) * 100.0, 2)
        return rate
