"""Unit tests for schema auto-mapping engine."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schema_mapper import apply_mapping_and_normalize, map_columns, normalize_date_column


def test_schema_mapper_exact_and_synonym():
    """Test exact match and synonym rule-based mapping fast pass."""
    uploaded_df = pd.DataFrame({
        "Txn ID": ["T100"],
        "InvoiceDate": ["2026-08-01"],
        "Credit Amount": [150.0],
        "Reference ID": ["REF100"],
        "Details": ["Payout text"],
    })

    target_schema = ["txn_id", "date", "amount", "reference_id", "description"]

    mapping, conf = map_columns(uploaded_df, target_schema, api_key="")

    assert mapping["Txn ID"] == "txn_id"
    assert mapping["InvoiceDate"] == "date"
    assert mapping["Credit Amount"] == "amount"
    assert mapping["Reference ID"] == "reference_id"
    assert mapping["Details"] == "description"

    assert conf["Txn ID"] >= 0.95
    assert conf["InvoiceDate"] >= 0.95
    assert conf["Credit Amount"] >= 0.95


def test_schema_mapper_llm_fallback():
    """Test ambiguous column mapping via LLM API call fallback."""
    uploaded_df = pd.DataFrame({
        "CustomMysteryCol": ["Val1", "Val2"],
    })

    target_schema = ["description"]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"mappings": {"CustomMysteryCol": "description"}, "confidence": {"CustomMysteryCol": 0.85}}'
        mock_msg.content = [mock_block]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic.return_value = mock_client

        mapping, conf = map_columns(uploaded_df, target_schema, api_key="mock_key")

        assert mapping["CustomMysteryCol"] == "description"
        assert conf["CustomMysteryCol"] == 0.85


def test_schema_mapper_unmappable():
    """Test unmappable columns correctly marked as 'unmapped'."""
    uploaded_df = pd.DataFrame({
        "IrrelevantGarbageHeader": [1, 2, 3],
    })

    target_schema = ["amount", "date"]

    mapping, conf = map_columns(uploaded_df, target_schema, api_key="")

    assert mapping["IrrelevantGarbageHeader"] == "unmapped"
    assert conf["IrrelevantGarbageHeader"] == 0.0


def test_date_normalization():
    """Test date normalization helper on different date formats."""
    dates_series = pd.Series(["15/08/2026", "2026-08-15", "08-15-2026"])
    normalized = normalize_date_column(dates_series)

    assert normalized[0] == "2026-08-15"
    assert normalized[1] == "2026-08-15"
