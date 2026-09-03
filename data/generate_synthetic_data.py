"""Synthetic Data Generator for AI Finance Controller.

Generates bank_statement.csv, settlement_report.csv, internal_ledger.csv,
and ground_truth.json with a fixed seed for reproducible evaluation.
"""

import json
import random
from datetime import datetime, timedelta
import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA_DIR, FEE_SCHEDULE


def generate_synthetic_dataset(seed: int = 42, num_base_records: int = 50) -> None:
    """Generates 3 synthetic financial data CSV files and a hidden ground truth evaluation file.

    Args:
        seed (int): Random seed for reproducibility (default 42).
        num_base_records (int): Baseline number of clean records to generate (default 50).

    Returns:
        None
    """
    random.seed(seed)
    DATA_DIR.mkdir(exist_ok=True, parents=True)

    base_date = datetime(2026, 8, 1)

    bank_records = []
    settlement_records = []
    ledger_records = []
    ground_truth = {}

    # Helper fee function: net = gross - fee (where fee = 2% gross + 18% GST on fee)
    def calc_fee(gross: float) -> tuple[float, float]:
        fee = round(gross * FEE_SCHEDULE["standard_rate"] * (1 + FEE_SCHEDULE["gst_rate"]), 2)
        net = round(gross - fee, 2)
        return fee, net

    txn_counter = 1000

    # ---------------------------------------------------------
    # 1. Clean 1:1:1 Records (~35 records)
    # ---------------------------------------------------------
    for i in range(35):
        txn_counter += 1
        ref_id = f"REF{txn_counter}"
        order_id = f"ORD{txn_counter}"
        txn_id = f"TXN{txn_counter}"
        settlement_id = f"STL{txn_counter}"
        
        amount = round(random.uniform(100.0, 5000.0), 2)
        txn_date = base_date + timedelta(days=random.randint(0, 10))
        fee, net = calc_fee(amount)
        cust_ref = f"CUST_{random.randint(100, 999)}"

        # Ledger record
        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "customer_ref": cust_ref,
            "status": "SETTLED"
        })

        # Settlement record
        settlement_records.append({
            "settlement_id": settlement_id,
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_id,
            "order_id": order_id
        })

        # Bank record (settlement payout)
        bank_records.append({
            "txn_id": txn_id,
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": net,
            "reference_id": ref_id,
            "description": f"Payout Razorpay {settlement_id} {ref_id}"
        })

        ground_truth[ref_id] = {
            "expected_match": True,
            "true_category": "exact_match",
            "notes": "Clean standard transaction",
            "related_ids": [order_id, txn_id, settlement_id]
        }

    # ---------------------------------------------------------
    # 2. Injected Anomalies (15-20% of records)
    # ---------------------------------------------------------

    # Case A: 3-4 Many-to-One Bundled Payouts
    # One settlement record net_amount equals sum of 2-3 internal_ledger records
    for b in range(3):
        bundle_size = 2 if b % 2 == 0 else 3
        bundle_orders = []
        bundle_gross = 0.0
        bundle_net = 0.0
        bundle_fee = 0.0
        bundle_ref = f"REF_BUNDLE_{b+1}"
        bundle_stl = f"STL_BUNDLE_{b+1}"
        bundle_cust = f"CUST_CORP_{b+1}"
        bundle_date = base_date + timedelta(days=12 + b)

        for j in range(bundle_size):
            txn_counter += 1
            o_id = f"ORD{txn_counter}"
            sub_amt = round(random.uniform(200.0, 1500.0), 2)
            f, n = calc_fee(sub_amt)
            bundle_gross += sub_amt
            bundle_fee += f
            bundle_net += n
            bundle_orders.append(o_id)

            ledger_records.append({
                "order_id": o_id,
                "date": bundle_date.strftime("%Y-%m-%d"),
                "amount": sub_amt,
                "customer_ref": bundle_cust,
                "status": "SETTLED"
            })

        bundle_gross = round(bundle_gross, 2)
        bundle_fee = round(bundle_fee, 2)
        bundle_net = round(bundle_net, 2)

        settlement_records.append({
            "settlement_id": bundle_stl,
            "date": (bundle_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": bundle_gross,
            "fee": bundle_fee,
            "net_amount": bundle_net,
            "reference_id": bundle_ref,
            "order_id": f"MULTI_{','.join(bundle_orders)}"
        })

        bank_records.append({
            "txn_id": f"TXN_BUNDLE_{b+1}",
            "date": (bundle_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": bundle_net,
            "reference_id": bundle_ref,
            "description": f"Bulk Settlement {bundle_stl} {bundle_ref}"
        })

        ground_truth[bundle_ref] = {
            "expected_match": True,
            "true_category": "many_to_one",
            "notes": f"Bundled payout of {bundle_size} orders: {bundle_orders}",
            "related_ids": bundle_orders + [bundle_stl]
        }

    # Case B: Fee Adjustment Discrepancies (2 records)
    for f_idx in range(2):
        txn_counter += 1
        ref_id = f"REF_FEE_{f_idx+1}"
        order_id = f"ORD{txn_counter}"
        amount = round(random.uniform(800.0, 3000.0), 2)
        txn_date = base_date + timedelta(days=15 + f_idx)
        std_fee, net = calc_fee(amount)
        # Apply non-standard promo fee (e.g. 1% instead of 2%)
        actual_fee = round(amount * 0.01 * 1.18, 2)
        actual_net = round(amount - actual_fee, 2)

        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "customer_ref": f"CUST_FEE_{f_idx}",
            "status": "SETTLED"
        })

        settlement_records.append({
            "settlement_id": f"STL_FEE_{f_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": amount,
            "fee": actual_fee,
            "net_amount": actual_net,
            "reference_id": ref_id,
            "order_id": order_id
        })

        bank_records.append({
            "txn_id": f"TXN_FEE_{f_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": actual_net,
            "reference_id": ref_id,
            "description": f"Payout Promo Rate {ref_id}"
        })

        ground_truth[ref_id] = {
            "expected_match": True,
            "true_category": "fee_adjustment",
            "notes": "Custom fee rate 1% GST applied instead of 2%",
            "related_ids": [order_id]
        }

    # Case C: 2-3 Day Timing Drift (2 records)
    for t_idx in range(2):
        txn_counter += 1
        ref_id = f"REF_DRIFT_{t_idx+1}"
        order_id = f"ORD{txn_counter}"
        amount = round(random.uniform(500.0, 2000.0), 2)
        txn_date = base_date + timedelta(days=5)
        fee, net = calc_fee(amount)

        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "customer_ref": "CUST_DRIFT",
            "status": "SETTLED"
        })

        settlement_records.append({
            "settlement_id": f"STL_DRIFT_{t_idx+1}",
            "date": (txn_date + timedelta(days=4)).strftime("%Y-%m-%d"),  # 4 day drift!
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_id,
            "order_id": order_id
        })

        bank_records.append({
            "txn_id": f"TXN_DRIFT_{t_idx+1}",
            "date": (txn_date + timedelta(days=5)).strftime("%Y-%m-%d"),
            "amount": net,
            "reference_id": ref_id,
            "description": f"Delayed Payout {ref_id}"
        })

        ground_truth[ref_id] = {
            "expected_match": True,
            "true_category": "timing_drift",
            "notes": "Settlement delayed by 4 days due to bank holiday",
            "related_ids": [order_id]
        }

    # Case D: Duplicate Reference IDs (2 records)
    for d_idx in range(2):
        txn_counter += 1
        ref_id = f"REF_DUP_999"  # Shared duplicate reference
        order_id = f"ORD{txn_counter}"
        amount = round(random.uniform(1000.0, 2500.0), 2)
        txn_date = base_date + timedelta(days=18)
        fee, net = calc_fee(amount)

        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "customer_ref": f"CUST_DUP_{d_idx}",
            "status": "SETTLED"
        })

        settlement_records.append({
            "settlement_id": f"STL_DUP_{d_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_id,
            "order_id": order_id
        })

        bank_records.append({
            "txn_id": f"TXN_DUP_{d_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": net,
            "reference_id": ref_id,
            "description": f"Payout Dup Ref {ref_id}"
        })

        ground_truth[f"{ref_id}_{order_id}"] = {
            "expected_match": True,
            "true_category": "duplicate_reference",
            "notes": "Duplicate reference ID reused across distinct orders",
            "related_ids": [order_id]
        }

    # Case E: Typo Reference IDs (2 records)
    typo_pairs = [("REF_TYPO_888", "REF_TIPO_888"), ("REF_TYPO_777", "REF_TYP0_777")]
    for typ_idx, (ref_orig, ref_typo) in enumerate(typo_pairs):
        txn_counter += 1
        order_id = f"ORD{txn_counter}"
        amount = round(random.uniform(400.0, 1800.0), 2)
        txn_date = base_date + timedelta(days=20)
        fee, net = calc_fee(amount)

        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "customer_ref": "CUST_TYPO",
            "status": "SETTLED"
        })

        settlement_records.append({
            "settlement_id": f"STL_TYPO_{typ_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_typo,  # Typo in settlement!
            "order_id": order_id
        })

        bank_records.append({
            "txn_id": f"TXN_TYPO_{typ_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": net,
            "reference_id": ref_typo,
            "description": f"Payout Typo {ref_typo}"
        })

        ground_truth[ref_typo] = {
            "expected_match": True,
            "true_category": "typo_reference_id",
            "notes": f"Typo in reference ID: {ref_typo} vs intended {ref_orig}",
            "related_ids": [order_id]
        }

    # Case F: Partial Refund (2 records)
    for p_idx in range(2):
        txn_counter += 1
        ref_id = f"REF_PARTIAL_{p_idx+1}"
        order_id = f"ORD{txn_counter}"
        gross_amount = 2000.0
        partial_gross = 1500.0  # $500 partial refund before settlement
        txn_date = base_date + timedelta(days=22)
        fee, net = calc_fee(partial_gross)

        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": gross_amount,
            "customer_ref": "CUST_PARTIAL",
            "status": "PARTIALLY_REFUNDED"
        })

        settlement_records.append({
            "settlement_id": f"STL_PARTIAL_{p_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": partial_gross,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_id,
            "order_id": order_id
        })

        bank_records.append({
            "txn_id": f"TXN_PARTIAL_{p_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": net,
            "reference_id": ref_id,
            "description": f"Payout Partial Refund {ref_id}"
        })

        ground_truth[ref_id] = {
            "expected_match": True,
            "true_category": "partial_refund",
            "notes": "Partial refund processed before payout settlement",
            "related_ids": [order_id]
        }

    # Case G: Currency Rounding Differences (2 records)
    for r_idx in range(2):
        txn_counter += 1
        ref_id = f"REF_ROUND_{r_idx+1}"
        order_id = f"ORD{txn_counter}"
        amount = round(random.uniform(300.0, 1200.0), 2)
        txn_date = base_date + timedelta(days=24)
        fee, net = calc_fee(amount)

        ledger_records.append({
            "order_id": order_id,
            "date": txn_date.strftime("%Y-%m-%d"),
            "amount": amount,
            "customer_ref": "CUST_ROUND",
            "status": "SETTLED"
        })

        settlement_records.append({
            "settlement_id": f"STL_ROUND_{r_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_id,
            "order_id": order_id
        })

        bank_records.append({
            "txn_id": f"TXN_ROUND_{r_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": net + 0.03,  # 3 cents FX / rounding drift in bank
            "reference_id": ref_id,
            "description": f"Payout Rounding {ref_id}"
        })

        ground_truth[ref_id] = {
            "expected_match": True,
            "true_category": "currency_rounding",
            "notes": "3 cents rounding variance due to foreign currency conversion",
            "related_ids": [order_id]
        }

    # Case H: Genuinely Unresolvable Records (3 records)
    for u_idx in range(3):
        txn_counter += 1
        ref_id = f"REF_UNRESOLVED_{u_idx+1}"
        stl_id = f"STL_UNRESOLVED_{u_idx+1}"
        amount = round(random.uniform(500.0, 3000.0), 2)
        txn_date = base_date + timedelta(days=25)
        fee, net = calc_fee(amount)

        # Record appears ONLY in settlement report & bank statement, missing from internal ledger
        settlement_records.append({
            "settlement_id": stl_id,
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "reference_id": ref_id,
            "order_id": f"ORD_GHOST_{u_idx+1}"
        })

        bank_records.append({
            "txn_id": f"TXN_UNRESOLVED_{u_idx+1}",
            "date": (txn_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "amount": net,
            "reference_id": ref_id,
            "description": f"Orphaned Payout {ref_id}"
        })

        ground_truth[ref_id] = {
            "expected_match": False,
            "true_category": "unresolved",
            "notes": "Orphaned transaction present in bank/settlement but absent from ledger",
            "related_ids": []
        }

    # Convert to DataFrames and save as CSV
    pd.DataFrame(bank_records).to_csv(DATA_DIR / "bank_statement.csv", index=False)
    pd.DataFrame(settlement_records).to_csv(DATA_DIR / "settlement_report.csv", index=False)
    pd.DataFrame(ledger_records).to_csv(DATA_DIR / "internal_ledger.csv", index=False)

    with open(DATA_DIR / "ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"Generated synthetic datasets in {DATA_DIR}:")
    print(f"  - bank_statement.csv: {len(bank_records)} records")
    print(f"  - settlement_report.csv: {len(settlement_records)} records")
    print(f"  - internal_ledger.csv: {len(ledger_records)} records")
    print(f"  - ground_truth.json: {len(ground_truth)} truth entries")


if __name__ == "__main__":
    generate_synthetic_dataset()
