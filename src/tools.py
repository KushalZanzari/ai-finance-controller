"""Callable tools for the AI reasoning agent.

Exposes domain-specific financial calculations, fuzzy reference search, date window lookups,
and subset-sum calculations for LLM function calling.
"""

from datetime import datetime, timedelta
import itertools
from typing import Any

from config.settings import DATE_WINDOW_DAYS, FEE_SCHEDULE
from src.matcher import levenshtein_distance


def check_fee_schedule(gross_amount: float) -> dict[str, float]:
    """Calculates expected payment gateway fees and net payout amount based on the standard fee schedule.

    Args:
        gross_amount (float): The gross transaction amount in INR.

    Returns:
        dict[str, float]: Dictionary containing gross_amount, gateway_fee, gst_on_fee, total_fee, and expected_net_amount.
    """
    gross = float(gross_amount)
    base_fee = gross * FEE_SCHEDULE["standard_rate"]
    gst = base_fee * FEE_SCHEDULE["gst_rate"]
    total_fee = round(base_fee + gst, 2)
    expected_net = round(gross - total_fee, 2)

    return {
        "gross_amount": gross,
        "gateway_fee": round(base_fee, 2),
        "gst_on_fee": round(gst, 2),
        "total_fee": total_fee,
        "expected_net_amount": expected_net,
    }


def find_similar_reference_ids(
    reference_id: str,
    candidate_pool: list[str],
    threshold: int = 3,
) -> list[dict[str, Any]]:
    """Searches a candidate pool for reference IDs close to the target string based on edit distance.

    Args:
        reference_id (str): Target reference ID to match against.
        candidate_pool (list[str]): List of candidate reference or order strings.
        threshold (int): Maximum edit distance permitted (default 3).

    Returns:
        list[dict[str, Any]]: List of matching candidate dicts with 'candidate' and 'edit_distance'.
    """
    results = []
    target = str(reference_id).upper().strip()

    for cand in candidate_pool:
        cand_str = str(cand).upper().strip()
        dist = levenshtein_distance(target, cand_str)
        if dist <= threshold:
            results.append({
                "candidate": cand,
                "edit_distance": dist,
                "is_exact": dist == 0
            })

    results.sort(key=lambda x: x["edit_distance"])
    return results


def get_settlement_window(order_date: str) -> dict[str, str]:
    """Computes the expected settlement payout date range given an order date.

    Args:
        order_date (str): ISO date string (YYYY-MM-DD) of the transaction order.

    Returns:
        dict[str, str]: Expected minimum settlement date and maximum settlement date.
    """
    try:
        dt = datetime.strptime(str(order_date)[:10], "%Y-%m-%d")
        min_date = dt + timedelta(days=1)
        max_date = dt + timedelta(days=DATE_WINDOW_DAYS + 1)
        return {
            "order_date": dt.strftime("%Y-%m-%d"),
            "expected_min_settlement": min_date.strftime("%Y-%m-%d"),
            "expected_max_settlement": max_date.strftime("%Y-%m-%d"),
        }
    except ValueError:
        return {
            "error": f"Invalid date format: {order_date}. Expected YYYY-MM-DD."
        }


def sum_candidate_subsets(
    target_amount: float,
    candidate_pool: list[dict[str, Any]],
    tolerance: float = 0.05,
) -> list[dict[str, Any]]:
    """Identifies subsets of records from candidate_pool whose sum matches target_amount within tolerance.

    Args:
        target_amount (float): Target gross or net payout amount.
        candidate_pool (list[dict[str, Any]]): Candidate records, each containing an 'amount' key.
        tolerance (float): Allowed difference tolerance (default 0.05).

    Returns:
        list[dict[str, Any]]: List of valid combinations with total sum and constituent record IDs.
    """
    target = float(target_amount)
    valid_subsets = []

    # Check subset combinations of size 2 to 4
    for r in range(2, min(5, len(candidate_pool) + 1)):
        for combo in itertools.combinations(candidate_pool, r):
            total_sum = sum(float(c.get("amount", 0.0)) for c in combo)
            if abs(total_sum - target) <= tolerance:
                valid_subsets.append({
                    "subset_size": r,
                    "total_sum": round(total_sum, 2),
                    "target_amount": target,
                    "record_ids": [c.get("order_id") or c.get("reference_id") or str(i) for i, c in enumerate(combo)],
                    "constituent_records": list(combo),
                })

    return valid_subsets


# Expose schema array for Anthropic tool calling format
AGENT_TOOL_SCHEMAS = [
    {
        "name": "check_fee_schedule",
        "description": "Calculates expected payment gateway fees and net payout amount based on Razorpay standard fee schedule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gross_amount": {
                    "type": "number",
                    "description": "Gross order transaction amount in INR."
                }
            },
            "required": ["gross_amount"]
        }
    },
    {
        "name": "find_similar_reference_ids",
        "description": "Finds reference IDs in a candidate pool close to the target reference ID using edit distance (for typos/transpositions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "reference_id": {
                    "type": "string",
                    "description": "The reference ID to inspect for potential typos."
                },
                "candidate_pool": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of reference or order strings to search against."
                },
                "threshold": {
                    "type": "integer",
                    "description": "Max edit distance (default 3)."
                }
            },
            "required": ["reference_id", "candidate_pool"]
        }
    },
    {
        "name": "get_settlement_window",
        "description": "Computes expected minimum and maximum settlement payout dates for a given transaction order date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_date": {
                    "type": "string",
                    "description": "Order date in YYYY-MM-DD format."
                }
            },
            "required": ["order_date"]
        }
    },
    {
        "name": "sum_candidate_subsets",
        "description": "Finds combinations of candidate ledger transactions that sum to a target settlement amount (many-to-one detection).",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_amount": {
                    "type": "number",
                    "description": "Target settlement amount to sum towards."
                },
                "candidate_pool": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of candidate objects with 'amount' fields."
                }
            },
            "required": ["target_amount", "candidate_pool"]
        }
    }
]
