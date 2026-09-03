"""Exception taxonomy definitions for financial reconciliation."""

from enum import Enum


class ExceptionCategory(str, Enum):
    """Categorized taxonomy of financial reconciliation outcomes and exceptions."""
    EXACT_MATCH = "exact_match"
    TIMING_DRIFT = "timing_drift"
    FEE_ADJUSTMENT = "fee_adjustment"
    PARTIAL_REFUND = "partial_refund"
    DUPLICATE_REFERENCE = "duplicate_reference"
    TYPO_REFERENCE_ID = "typo_reference_id"
    CURRENCY_ROUNDING = "currency_rounding"
    MANY_TO_ONE = "many_to_one"
    UNRESOLVED = "unresolved"


TAXONOMY_DESCRIPTIONS = {
    ExceptionCategory.EXACT_MATCH: "Exact 1:1 match across ledger, settlement report, and bank statement.",
    ExceptionCategory.TIMING_DRIFT: "Settlement delayed beyond standard settlement window (e.g. weekends/holidays).",
    ExceptionCategory.FEE_ADJUSTMENT: "Discrepancy caused by custom/promotional payment gateway fee rates or GST.",
    ExceptionCategory.PARTIAL_REFUND: "Settlement amount reduced due to a partial refund processed prior to payout.",
    ExceptionCategory.DUPLICATE_REFERENCE: "The same reference ID is reused across multiple distinct customer orders.",
    ExceptionCategory.TYPO_REFERENCE_ID: "Typographical or character transposition error in the reference ID.",
    ExceptionCategory.CURRENCY_ROUNDING: "Minor fraction/cent rounding discrepancy (e.g. FX conversion variance).",
    ExceptionCategory.MANY_TO_ONE: "Single settlement payout bundling multiple distinct internal ledger transactions.",
    ExceptionCategory.UNRESOLVED: "Record could not be matched with sufficient confidence; requires manual audit.",
}
