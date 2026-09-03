"""PII Masking module for stripping or redacting sensitive fields before LLM API calls."""

import re
from typing import Any

# Whitelisted field keys that should never have pattern redaction applied
SAFE_KEYS = {
    "amount",
    "gross_amount",
    "fee",
    "net_amount",
    "date",
    "reference_id",
    "order_id",
    "txn_id",
    "settlement_id",
    "status",
}

# Regex patterns for common PII shapes
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_REGEX = re.compile(r"\+?\b\d{1,4}[-.\s]\d{3}[-.\s]\d{4}\b")
CARD_ACCOUNT_REGEX = re.compile(r"\b\d{10,16}\b")


def mask_pii_string(value: str) -> str:
    """Applies rule-based regex patterns to redact emails, phone numbers, and account/card numbers.

    Args:
        value (str): Input text string.

    Returns:
        str: PII-masked string.
    """
    if not isinstance(value, str):
        return value

    # Avoid redacting YYYY-MM-DD dates
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value.strip()):
        return value

    # Mask email addresses
    masked = EMAIL_REGEX.sub("***@***.com", value)

    # Mask account / card numbers down to last 4 digits first (before phone regex)
    def _mask_account(match: re.Match) -> str:
        digits = match.group(0)
        return "****" + digits[-4:]

    masked = CARD_ACCOUNT_REGEX.sub(_mask_account, masked)

    # Mask phone numbers second
    masked = PHONE_REGEX.sub("[MASKED_PHONE]", masked)
    return masked


def mask_sensitive_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Strips or masks fields not required for financial matching before passing payload to LLM.

    Args:
        record (dict[str, Any]): Transaction or sample record dict.

    Returns:
        dict[str, Any]: Cleaned record dict with sensitive fields redacted.
    """
    if not isinstance(record, dict):
        return record

    masked_record = {}

    for key, value in record.items():
        key_lower = str(key).lower().strip()

        # Whitelisted keys pass through directly without string pattern matching
        if key_lower in SAFE_KEYS:
            masked_record[key] = value
            continue

        # Remove explicit customer names, emails, phones if non-whitelisted key
        if any(pii_kw in key_lower for pii_kw in ["customer_name", "full_name", "email", "phone", "ssn", "pan", "card_number"]):
            if "email" in key_lower:
                masked_record[key] = "***@***.com"
            elif "phone" in key_lower:
                masked_record[key] = "[MASKED_PHONE]"
            elif "card" in key_lower or "account" in key_lower:
                val_str = str(value)
                masked_record[key] = "****" + val_str[-4:] if len(val_str) >= 4 else "****"
            else:
                masked_record[key] = "[REDACTED_PII]"
            continue

        # Recursively handle nested dictionaries and lists
        if isinstance(value, dict):
            masked_record[key] = mask_sensitive_fields(value)
        elif isinstance(value, list):
            masked_record[key] = [
                mask_sensitive_fields(v) if isinstance(v, dict) else mask_pii_string(str(v))
                for v in value
            ]
        elif isinstance(value, str):
            masked_record[key] = mask_pii_string(value)
        else:
            masked_record[key] = value

    return masked_record
