"""Deterministic matching engine for financial reconciliation.

Handles exact matches, tolerance/window matches, bounded subset-sum many-to-one matches,
and outputs unmatched candidates paired with candidate matches for LLM agent investigation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import itertools
import time
from typing import Any

import pandas as pd
from config.settings import (
    AMOUNT_ROUNDING_TOLERANCE,
    DATE_WINDOW_DAYS,
    FEE_SCHEDULE,
)
from src.logging_config import logger


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates Levenshtein edit distance between two strings.

    Args:
        s1 (str): First string.
        s2 (str): Second string.

    Returns:
        int: Edit distance.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


@dataclass
class MatchResult:
    """Data structure representing a resolved or matched record."""
    settlement_id: str
    order_id: str
    reference_id: str
    match_type: str  # 'exact', 'many_to_one', 'agent_resolved', etc.
    confidence: float
    category: str
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CandidatePair:
    """Data structure representing an ambiguous record pair for agent reasoning."""
    settlement_record: dict[str, Any]
    candidate_ledger_records: list[dict[str, Any]]
    candidate_bank_records: list[dict[str, Any]]
    levenshtein_score: float
    amount_difference: float
    notes: str


class DeterministicMatcher:
    """Engine for performing deterministic reconciliation and candidate isolation."""

    def __init__(
        self,
        date_window_days: int = DATE_WINDOW_DAYS,
        amount_tolerance: float = AMOUNT_ROUNDING_TOLERANCE,
    ) -> None:
        """Initializes the matcher with window and tolerance thresholds.

        Args:
            date_window_days (int): Allowed date variance in days.
            amount_tolerance (float): Allowed amount variance in currency units.
        """
        self.date_window_days = date_window_days
        self.amount_tolerance = amount_tolerance

    def _dates_in_window(self, date_str1: str, date_str2: str) -> bool:
        """Checks if two ISO date strings fall within the configured date window."""
        try:
            d1 = datetime.strptime(str(date_str1)[:10], "%Y-%m-%d")
            d2 = datetime.strptime(str(date_str2)[:10], "%Y-%m-%d")
            return abs((d1 - d2).days) <= self.date_window_days
        except ValueError:
            return False

    def _amounts_match(self, amt1: float, amt2: float) -> bool:
        """Checks if two amounts match within configured tolerance."""
        return abs(float(amt1) - float(amt2)) <= self.amount_tolerance

    def run_deterministic_pass(
        self,
        bank_df: pd.DataFrame,
        settlement_df: pd.DataFrame,
        ledger_df: pd.DataFrame,
    ) -> tuple[list[MatchResult], list[CandidatePair], float, int]:
        """Runs the deterministic matching pass including exact and many-to-one passes.

        Args:
            bank_df (pd.DataFrame): Bank statement records.
            settlement_df (pd.DataFrame): Settlement report records.
            ledger_df (pd.DataFrame): Internal ledger records.

        Returns:
            tuple containing:
                - List of MatchResult objects for deterministic matches
                - List of CandidatePair objects for ambiguous cases needing LLM agent
                - Elapsed execution time in seconds
                - Total input record count
        """
        start_time = time.time()
        matches: list[MatchResult] = []
        unmatched_settlements: list[dict[str, Any]] = []

        total_records = len(settlement_df)
        logger.info(f"Starting deterministic pass over {total_records} settlement records...")

        # Convert to dictionary records for fast processing
        settlements = settlement_df.to_dict(orient="records")
        ledger_records = ledger_df.to_dict(orient="records")
        bank_records = bank_df.to_dict(orient="records")

        matched_ledger_ids: set[str] = set()
        matched_settlement_ids: set[str] = set()

        # ---------------------------------------------------------------------
        # Pass 1: Exact Reference / Order ID + Amount + Date Window
        # ---------------------------------------------------------------------
        for stl in settlements:
            stl_id = str(stl["settlement_id"])
            ref_id = str(stl.get("reference_id", ""))
            order_id = str(stl.get("order_id", ""))
            net_amt = float(stl.get("net_amount", 0.0))
            gross_amt = float(stl.get("gross_amount", 0.0))
            stl_date = str(stl.get("date", ""))

            # Look for direct match in internal ledger by order_id or ref_id
            direct_match = None
            for leg in ledger_records:
                leg_order_id = str(leg.get("order_id", ""))
                leg_amt = float(leg.get("amount", 0.0))
                leg_date = str(leg.get("date", ""))

                if leg_order_id in matched_ledger_ids:
                    continue

                # Check if order matches and amount matches either gross or net (fee-adjusted)
                if (leg_order_id == order_id or ref_id in leg_order_id) and self._dates_in_window(stl_date, leg_date):
                    # Check gross match or exact net match
                    if self._amounts_match(leg_amt, gross_amt):
                        direct_match = leg
                        break

            if direct_match:
                matched_ledger_ids.add(str(direct_match["order_id"]))
                matched_settlement_ids.add(stl_id)
                matches.append(
                    MatchResult(
                        settlement_id=stl_id,
                        order_id=str(direct_match["order_id"]),
                        reference_id=ref_id,
                        match_type="exact",
                        confidence=1.0,
                        category="exact_match",
                        explanation=f"Exact match on order {direct_match['order_id']} and gross amount {gross_amt}",
                        details={"settlement": stl, "ledger": direct_match},
                    )
                )
            else:
                unmatched_settlements.append(stl)

        logger.info(f"Pass 1 complete. Found {len(matches)} exact matches.")

        # ---------------------------------------------------------------------
        # Pass 2: Bounded Subset-Sum Search (Many-to-One Matches)
        # ---------------------------------------------------------------------
        still_unmatched_settlements = []
        unmatched_ledger = [l for l in ledger_records if str(l["order_id"]) not in matched_ledger_ids]

        for stl in unmatched_settlements:
            stl_id = str(stl["settlement_id"])
            ref_id = str(stl.get("reference_id", ""))
            target_net = float(stl.get("net_amount", 0.0))
            target_gross = float(stl.get("gross_amount", 0.0))
            stl_date = str(stl.get("date", ""))

            # Filter remaining candidate ledger entries within date proximity
            date_candidates = [
                l for l in unmatched_ledger
                if str(l["order_id"]) not in matched_ledger_ids
                and self._dates_in_window(stl_date, str(l.get("date", "")))
            ]

            # Sort candidate pool by amount proximity and cap to top 30 to bound O(N^4) subset-sum runtime
            date_candidates.sort(key=lambda x: abs(float(x.get("amount", 0.0)) - target_gross))
            date_candidates = date_candidates[:30]

            found_subset = None
            # Check subsets of size 2 to 4
            for r in range(2, min(5, len(date_candidates) + 1)):
                for combo in itertools.combinations(date_candidates, r):
                    combo_gross = sum(float(c["amount"]) for c in combo)
                    # Also compute fee-adjusted net sum
                    fee_pct = FEE_SCHEDULE["standard_rate"] * (1 + FEE_SCHEDULE["gst_rate"])
                    combo_net = round(combo_gross * (1 - fee_pct), 2)

                    if self._amounts_match(combo_gross, target_gross) or self._amounts_match(combo_net, target_net):
                        found_subset = combo
                        break
                if found_subset:
                    break

            if found_subset:
                matched_settlement_ids.add(stl_id)
                bundled_orders = [str(c["order_id"]) for c in found_subset]
                for c in found_subset:
                    matched_ledger_ids.add(str(c["order_id"]))

                matches.append(
                    MatchResult(
                        settlement_id=stl_id,
                        order_id=",".join(bundled_orders),
                        reference_id=ref_id,
                        match_type="many_to_one",
                        confidence=0.9,
                        category="many_to_one",
                        explanation=f"Bundled payout matching {len(bundled_orders)} ledger entries sum to net amount {target_net}",
                        details={"settlement": stl, "bundled_ledger_records": found_subset},
                    )
                )
            else:
                still_unmatched_settlements.append(stl)

        logger.info(f"Pass 2 (Many-to-One) complete. Total matches now: {len(matches)}")

        # ---------------------------------------------------------------------
        # Pass 3: Candidate Pair Generation for LLM Agent
        # ---------------------------------------------------------------------
        candidates_for_agent: list[CandidatePair] = []
        remaining_ledger = [l for l in ledger_records if str(l["order_id"]) not in matched_ledger_ids][:1000]

        for stl in still_unmatched_settlements:
            ref_id = str(stl.get("reference_id", ""))
            stl_gross = float(stl.get("gross_amount", 0.0))

            # Rank remaining ledger entries by Levenshtein distance & amount proximity
            scored_ledger = []
            for leg in remaining_ledger:
                leg_order_id = str(leg.get("order_id", ""))
                dist = levenshtein_distance(ref_id, leg_order_id)
                amt_diff = abs(float(leg.get("amount", 0.0)) - stl_gross)
                scored_ledger.append((dist, amt_diff, leg))

            # Sort by edit distance first, then amount difference
            scored_ledger.sort(key=lambda x: (x[0], x[1]))
            top_ledger = [x[2] for x in scored_ledger[:3]]

            # Match corresponding bank statements
            scored_bank = []
            for bnk in bank_records:
                bnk_ref = str(bnk.get("reference_id", ""))
                dist = levenshtein_distance(ref_id, bnk_ref)
                scored_bank.append((dist, bnk))

            scored_bank.sort(key=lambda x: x[0])
            top_bank = [x[1] for x in scored_bank[:2]]

            best_dist = scored_ledger[0][0] if scored_ledger else 99
            best_amt_diff = scored_ledger[0][1] if scored_ledger else 999.0

            candidates_for_agent.append(
                CandidatePair(
                    settlement_record=stl,
                    candidate_ledger_records=top_ledger,
                    candidate_bank_records=top_bank,
                    levenshtein_score=float(best_dist),
                    amount_difference=float(best_amt_diff),
                    notes=f"Unmatched in deterministic pass. Best ref distance: {best_dist}",
                )
            )

        elapsed = time.time() - start_time
        logger.info(f"Deterministic pass done in {elapsed:.4f}s. Matches: {len(matches)}, Ambiguous Candidates: {len(candidates_for_agent)}")
        return matches, candidates_for_agent, elapsed, total_records
