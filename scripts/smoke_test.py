"""Smoke test script for verifying clean pipeline execution end-to-end."""

import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def run_smoke_test() -> None:
    """Executes end-to-end smoke test verifying data generation and pipeline execution."""
    print("=========================================================")
    print("Starting AI Finance Controller Smoke Test")
    print("=========================================================")

    # 1. Run synthetic data generator
    print("\n[1/3] Generating synthetic datasets...")
    gen_script = BASE_DIR / "data" / "generate_synthetic_data.py"
    res_gen = subprocess.run([sys.executable, str(gen_script)], cwd=BASE_DIR, capture_output=True, text=True)

    if res_gen.returncode != 0:
        print(f"FAILED: Data generation script error:\n{res_gen.stderr}")
        sys.exit(1)
    print("  -> Data generation completed successfully.")

    # 2. Run full pipeline
    print("\n[2/3] Executing full reconciliation pipeline...")
    pipe_script = BASE_DIR / "src" / "pipeline.py"
    res_pipe = subprocess.run([sys.executable, str(pipe_script)], cwd=BASE_DIR, capture_output=True, text=True)

    if res_pipe.returncode != 0:
        print(f"FAILED: Pipeline execution error:\n{res_pipe.stderr}")
        sys.exit(1)
    print("  -> Pipeline execution completed successfully.")

    # 3. Verify output files
    print("\n[3/3] Verifying output artifacts...")
    summary_path = BASE_DIR / "outputs" / "summary_metrics.json"
    exceptions_path = BASE_DIR / "outputs" / "exceptions_report.json"

    if not summary_path.exists():
        print(f"FAILED: Missing output file {summary_path}")
        sys.exit(1)

    if not exceptions_path.exists():
        print(f"FAILED: Missing output file {exceptions_path}")
        sys.exit(1)

    with open(summary_path, "r") as f:
        metrics = json.load(f)

    with open(exceptions_path, "r") as f:
        exceptions = json.load(f)

    base_rate = metrics.get("baseline_match_rate", 0)
    full_rate = metrics.get("full_pipeline_match_rate", 0)
    records_cnt = metrics.get("total_records_processed", 0)

    print(f"  -> Processed Records: {records_cnt}")
    print(f"  -> Baseline Match Rate: {base_rate}%")
    print(f"  -> Full Pipeline Match Rate: {full_rate}%")
    print(f"  -> Exceptions Count: {len(exceptions)}")

    print("\n=========================================================")
    print("[SUCCESS] SMOKE TEST PASSED 100%! All outputs produced cleanly.")
    print("=========================================================")


if __name__ == "__main__":
    run_smoke_test()
