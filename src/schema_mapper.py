"""Schema auto-mapping engine for aligning arbitrary uploaded CSV columns to target pipeline schemas."""

import json
from typing import Any
import pandas as pd
from dateutil import parser as date_parser

from config.settings import ANTHROPIC_API_KEY, LLM_MODEL_NAME
from src.logging_config import logger
from src.pii_masking import mask_sensitive_fields

# Optional anthropic import
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# Dictionary of standard column synonyms for rule-based fast pass matching
COLUMN_SYNONYMS = {
    "txn_id": ["txn_id", "txn id", "transaction_id", "transaction id", "invoice id", "invoiceno", "utr", "transaction reference"],
    "date": ["date", "txn_date", "invoice_date", "invoicedate", "settlement date", "created date", "order_date", "created_at", "timestamp"],
    "amount": ["amount", "credit", "credit amount", "sales", "total", "total amount", "amount (inr)", "line total", "price", "unitprice", "quantity"],
    "reference_id": ["reference_id", "reference id", "reference", "ref id", "utr number", "utr", "ref_no"],
    "description": ["description", "details", "narrative", "memo", "desc", "product_description"],
    "settlement_id": ["settlement_id", "settlement id", "payout id", "payment payout id", "settlement_no"],
    "gross_amount": ["gross_amount", "gross", "gross amount", "total sales", "gross (inr)"],
    "fee": ["fee", "gateway fee", "deducted fee", "tax 5%", "gst", "service fee", "tax"],
    "net_amount": ["net_amount", "net", "net payout", "net amount", "net credit"],
    "order_id": ["order_id", "order id", "order number", "order_no", "invoice_no"],
    "customer_ref": ["customer_ref", "customer ref", "customer id", "customerid", "customer"],
    "status": ["status", "state", "order status", "txn_status"],
}


def normalize_date_column(series: pd.Series) -> pd.Series:
    """Normalizes a Series of arbitrary date strings into standard YYYY-MM-DD format.

    Args:
        series (pd.Series): Input pandas Series containing date values.

    Returns:
        pd.Series: Normalized pandas Series with YYYY-MM-DD date strings.
    """
    def _parse_date(val: Any) -> str:
        if pd.isna(val) or not val:
            return "2026-08-01"
        val_str = str(val).strip()
        try:
            parsed = date_parser.parse(val_str)
            return parsed.strftime("%Y-%m-%d")
        except Exception:
            return val_str[:10]

    return series.apply(_parse_date)


def map_columns(
    uploaded_df: pd.DataFrame,
    target_schema: list[str],
    api_key: str = ANTHROPIC_API_KEY,
    model: str = LLM_MODEL_NAME,
) -> tuple[dict[str, str], dict[str, float]]:
    """Maps uploaded DataFrame columns to target schema fields using rule-based synonyms and LLM fallback.

    Args:
        uploaded_df (pd.DataFrame): Uploaded input DataFrame.
        target_schema (list[str]): Target field names to map towards.
        api_key (str): Anthropic API key for LLM fallback calls.
        model (str): LLM model name string.

    Returns:
        tuple[dict[str, str], dict[str, float]]:
            - Column mapping dict: {"uploaded_col": "target_field"}
            - Confidence scores dict: {"uploaded_col": confidence_float_0_to_1}
    """
    column_mapping: dict[str, str] = {}
    confidence_scores: dict[str, float] = {}

    unmapped_columns: list[str] = []

    # -------------------------------------------------------------------------
    # Rule 1 & 2: Rule-based fast pass (Case-insensitive exact matches + Synonyms)
    # -------------------------------------------------------------------------
    for col in uploaded_df.columns:
        col_clean = str(col).lower().strip()
        col_snake = col_clean.replace(" ", "_")

        # Check exact match against target schema
        if col_snake in target_schema:
            column_mapping[col] = col_snake
            confidence_scores[col] = 1.0
            continue

        # Check exact match in synonyms dictionary
        matched_target = None
        for target_field, synonyms in COLUMN_SYNONYMS.items():
            if target_field in target_schema and col_clean in synonyms:
                matched_target = target_field
                break

        if matched_target:
            column_mapping[col] = matched_target
            confidence_scores[col] = 0.95
        else:
            unmapped_columns.append(col)

    # -------------------------------------------------------------------------
    # Rule 3: LLM-assisted mapping for remaining unmapped columns
    # -------------------------------------------------------------------------
    if unmapped_columns and HAS_ANTHROPIC and api_key:
        logger.info(f"Invoking LLM to assist mapping for {len(unmapped_columns)} unmapped columns: {unmapped_columns}")
        
        # Extract first 5 sample rows and pass through PII masking
        sample_rows = uploaded_df[unmapped_columns].head(5).to_dict(orient="records")
        masked_samples = [mask_sensitive_fields(r) for r in sample_rows]

        system_prompt = (
            "You are a schema auto-mapping AI assistant.\n"
            "Map each uploaded column name to the single best matching target schema field from the target list.\n"
            "If an uploaded column does NOT fit any target field, map it to 'unmapped'.\n"
            "Return ONLY a JSON object with this exact structure:\n"
            "{\n"
            '  "mappings": {"uploaded_column": "target_field"},\n'
            '  "confidence": {"uploaded_column": 0.85}\n'
            "}"
        )

        user_prompt = (
            f"Target Schema Fields: {json.dumps(target_schema)}\n"
            f"Unmapped Uploaded Columns: {json.dumps(unmapped_columns)}\n"
            f"PII-Masked Sample Rows (First 5): {json.dumps(masked_samples)}"
        )

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=10,
            )

            text_content = ""
            for block in response.content:
                if block.type == "text":
                    text_content += block.text

            json_str = text_content.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()

            llm_result = json.loads(json_str)
            llm_maps = llm_result.get("mappings", {})
            llm_confs = llm_result.get("confidence", {})

            for col in unmapped_columns:
                target_field = llm_maps.get(col, "unmapped")
                conf = float(llm_confs.get(col, 0.70))
                column_mapping[col] = target_field
                confidence_scores[col] = conf if target_field != "unmapped" else 0.0

        except Exception as e:
            logger.warning(f"LLM column mapping API call failed: {e}. Defaulting remaining columns to unmapped.")
            for col in unmapped_columns:
                column_mapping[col] = "unmapped"
                confidence_scores[col] = 0.0
    else:
        # Local fallback for remaining unmapped columns
        for col in unmapped_columns:
            column_mapping[col] = "unmapped"
            confidence_scores[col] = 0.0

    return column_mapping, confidence_scores


def apply_mapping_and_normalize(
    df: pd.DataFrame,
    column_mapping: dict[str, str],
) -> pd.DataFrame:
    """Applies column mapping and normalizes date columns in a DataFrame.

    Args:
        df (pd.DataFrame): Raw input DataFrame.
        column_mapping (dict[str, str]): Mapping from uploaded columns to target fields.

    Returns:
        pd.DataFrame: Processed DataFrame with target column names and normalized dates.
    """
    mapped_df = df.copy()

    # Filter out 'unmapped' columns and rename mapped ones
    valid_rename = {k: v for k, v in column_mapping.items() if v != "unmapped"}
    mapped_df = mapped_df.rename(columns=valid_rename)

    # Normalize date column if present
    if "date" in mapped_df.columns:
        mapped_df["date"] = normalize_date_column(mapped_df["date"])

    return mapped_df
