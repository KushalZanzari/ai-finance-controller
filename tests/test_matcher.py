"""Unit tests for deterministic matcher engine."""

import sys
from pathlib import Path
import pandas as pd
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.matcher import DeterministicMatcher, levenshtein_distance


def test_levenshtein_distance():
    """Test Levenshtein distance string similarity calculations."""
    assert levenshtein_distance("REF1001", "REF1001") == 0
    assert levenshtein_distance("REF1001", "REF1002") == 1
    assert levenshtein_distance("REF_TYPO", "REF_TIPO") == 1
    assert levenshtein_distance("", "REF") == 3


def test_deterministic_exact_match():
    """Test exact match logic on order_id and amount."""
    matcher = DeterministicMatcher()

    bank_df = pd.DataFrame([{
        "txn_id": "TXN1",
        "date": "2026-08-02",
        "amount": 980.0,
        "reference_id": "REF1001",
        "description": "Payout REF1001"
    }])

    settlement_df = pd.DataFrame([{
        "settlement_id": "STL1001",
        "date": "2026-08-02",
        "gross_amount": 1000.0,
        "fee": 20.0,
        "net_amount": 980.0,
        "reference_id": "REF1001",
        "order_id": "ORD1001"
    }])

    ledger_df = pd.DataFrame([{
        "order_id": "ORD1001",
        "date": "2026-08-01",
        "amount": 1000.0,
        "customer_ref": "CUST1",
        "status": "SETTLED"
    }])

    matches, candidates, elapsed, total = matcher.run_deterministic_pass(
        bank_df, settlement_df, ledger_df
    )

    assert len(matches) == 1
    assert matches[0].match_type == "exact"
    assert matches[0].confidence == 1.0
    assert matches[0].order_id == "ORD1001"
    assert len(candidates) == 0


def test_many_to_one_subset_match():
    """Test many-to-one subset sum matching for bundled payouts."""
    matcher = DeterministicMatcher()

    bank_df = pd.DataFrame([{
        "txn_id": "TXN_B1",
        "date": "2026-08-05",
        "amount": 290.0,
        "reference_id": "REF_BUNDLE",
        "description": "Payout REF_BUNDLE"
    }])

    # Net 290 equals sum of net payouts for 100 + 200 gross
    settlement_df = pd.DataFrame([{
        "settlement_id": "STL_B1",
        "date": "2026-08-05",
        "gross_amount": 300.0,
        "fee": 10.0,
        "net_amount": 290.0,
        "reference_id": "REF_BUNDLE",
        "order_id": "MULTI_ORD1,ORD2"
    }])

    ledger_df = pd.DataFrame([
        {
            "order_id": "ORD1",
            "date": "2026-08-04",
            "amount": 100.0,
            "customer_ref": "CUST_CORP",
            "status": "SETTLED"
        },
        {
            "order_id": "ORD2",
            "date": "2026-08-04",
            "amount": 200.0,
            "customer_ref": "CUST_CORP",
            "status": "SETTLED"
        }
    ])

    matches, candidates, elapsed, total = matcher.run_deterministic_pass(
        bank_df, settlement_df, ledger_df
    )

    assert len(matches) == 1
    assert matches[0].match_type == "many_to_one"
    assert matches[0].confidence == 0.9
    assert "ORD1,ORD2" in matches[0].order_id or "ORD1" in matches[0].order_id


def test_empty_input_handling():
    """Test graceful handling of empty DataFrame inputs."""
    matcher = DeterministicMatcher()
    empty_df = pd.DataFrame(columns=["settlement_id", "gross_amount", "net_amount", "reference_id", "order_id", "date"])

    matches, candidates, elapsed, total = matcher.run_deterministic_pass(
        empty_df, empty_df, empty_df
    )

    assert len(matches) == 0
    assert len(candidates) == 0
    assert total == 0
