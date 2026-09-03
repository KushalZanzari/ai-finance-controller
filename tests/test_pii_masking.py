"""Unit tests for PII masking module."""

import json
import sys
from pathlib import Path
import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pii_masking import mask_pii_string, mask_sensitive_fields


def test_pii_string_patterns():
    """Test regex pattern masking for emails, phone numbers, and long account digits."""
    raw_text = "Contact john.doe@example.com or call +1 555-123-4567 regarding Account 4111222233334444."
    masked = mask_pii_string(raw_text)

    assert "john.doe@example.com" not in masked
    assert "***@***.com" in masked
    assert "+1 555-123-4567" not in masked
    assert "[MASKED_PHONE]" in masked
    assert "4111222233334444" not in masked
    assert "****4444" in masked


def test_mask_sensitive_fields_record():
    """Verify sensitive fields in record dict are masked while amounts, dates, and ref IDs pass through."""
    raw_record = {
        "order_id": "ORD1001",
        "date": "2026-08-01",
        "amount": 1250.50,
        "reference_id": "REF1001",
        "customer_name": "Alice Smith",
        "customer_email": "alice.smith@domain.org",
        "phone": "+91 9876543210",
        "card_number": "4532012345678901",
        "status": "SETTLED",
    }

    masked_record = mask_sensitive_fields(raw_record)

    # Whitelisted fields pass through
    assert masked_record["order_id"] == "ORD1001"
    assert masked_record["date"] == "2026-08-01"
    assert masked_record["amount"] == 1250.50
    assert masked_record["reference_id"] == "REF1001"
    assert masked_record["status"] == "SETTLED"

    # Sensitive fields are masked
    assert "alice.smith@domain.org" not in json.dumps(masked_record)
    assert "+91 9876543210" not in json.dumps(masked_record)
    assert "4532012345678901" not in json.dumps(masked_record)
    assert "****8901" in masked_record["card_number"]
