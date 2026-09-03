"""Unit tests for ReAct LLM Agent reasoning loop and tool execution."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm_agent import ReActReasoningAgent
from src.matcher import CandidatePair
from src.taxonomy import ExceptionCategory


def test_tool_call_loop_cap_and_fallback():
    """Verify tool call loop terminates within max tool calls cap and produces structured response."""
    agent = ReActReasoningAgent(api_key="")  # Empty API key triggers local ReAct tool loop

    candidate = CandidatePair(
        settlement_record={
            "settlement_id": "STL_TYPO_TEST",
            "date": "2026-08-05",
            "gross_amount": 1000.0,
            "fee": 23.6,
            "net_amount": 976.4,
            "reference_id": "REF_TYP0_999",  # Typo in ref
            "order_id": "ORD999",
        },
        candidate_ledger_records=[{
            "order_id": "ORD999",
            "date": "2026-08-04",
            "amount": 1000.0,
            "customer_ref": "CUST_TEST",
            "status": "SETTLED",
        }],
        candidate_bank_records=[{
            "txn_id": "TXN999",
            "date": "2026-08-05",
            "amount": 976.4,
            "reference_id": "REF_TYPO_999",
        }],
        levenshtein_score=1.0,
        amount_difference=0.0,
        notes="Unmatched candidate pair",
    )

    decision = agent.analyze_candidate_pair(candidate)

    # Check structure
    assert "is_match" in decision
    assert "confidence" in decision
    assert "category" in decision
    assert "explanation" in decision
    assert "tools_used" in decision

    # Tool calls must be capped at <= 4
    assert len(decision["tools_used"]) <= 4
    assert decision["category"] == ExceptionCategory.TYPO_REFERENCE_ID.value


def test_agent_api_failure_graceful_recovery():
    """Verify agent handles repeated API failures gracefully without crashing."""
    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        # Simulate API exception on create call
        mock_client.messages.create.side_effect = Exception("API Connection Timeout")
        mock_anthropic.return_value = mock_client

        agent = ReActReasoningAgent(api_key="mock_key")
        candidate = CandidatePair(
            settlement_record={"settlement_id": "STL_FAIL", "gross_amount": 500.0},
            candidate_ledger_records=[],
            candidate_bank_records=[],
            levenshtein_score=99.0,
            amount_difference=500.0,
            notes="Fail test",
        )

        decision = agent.analyze_candidate_pair(candidate)

        # Should return unresolved on failure rather than crashing
        assert decision["is_match"] is False
        assert decision["confidence"] == 0.0
        assert decision["category"] == ExceptionCategory.UNRESOLVED.value
