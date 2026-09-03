# AI Finance Controller - Architecture Overview

## System Architecture

```
                  ┌──────────────────────────────────────────┐
                  │ 1. Bank Statement (CSV)                  │
                  │ 2. Settlement Report (CSV)               │
                  │ 3. Internal Ledger (CSV)                 │
                  └────────────────────┬─────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────┐
                  │ STAGE 1: Deterministic Matcher           │
                  │ • Exact 1:1 Reference/Amount Match (1.0) │
                  │ • Bounded Subset-Sum Many-to-One (0.9)   │
                  └────────────────────┬─────────────────────┘
                                       │
                       Unmatched Ambiguous Candidates
                                       │
                                       ▼
                  ┌──────────────────────────────────────────┐
                  │ STAGE 2: ReAct LLM Agent Loop            │
                  │ • max 4 Tool Calls per record            │
                  │ • Fee schedule, edit dist, dates, sums   │
                  └────────────────────┬─────────────────────┘
                                       │
                                       ├──────────────────────────────┐
                    Confidence >= 70%  │                              │ Confidence < 70%
                                       ▼                              ▼
                  ┌──────────────────────────┐   ┌──────────────────────────┐
                  │ STAGE 3A: Auto-Accept    │   │ STAGE 3B: Human Review   │
                  │ Logged to Audit Trail    │   │ Interactive Queue        │
                  └────────────┬─────────────┘   └────────────┬─────────────┘
                               │                              │
                               └──────────────┬───────────────┘
                                              │
                                              ▼
                  ┌──────────────────────────────────────────┐
                  │ STAGE 4: Calibration & Accuracy Analysis │
                  │ Evaluates against hidden ground_truth    │
                  └────────────────────┬─────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────┐
                  │ STAGE 5: Reports & Streamlit Dashboard   │
                  │ summary_metrics.json & audit_trail.json  │
                  └──────────────────────────────────────────┘
```

## Core Components & Data Flow

1. **Deterministic Matcher (`src/matcher.py`)**:
   - Clears 80-85% of standard transactions deterministically at high throughput (~1000 rec/sec).
   - Solves many-to-one payout bundling (1 settlement = N ledger orders) via bounded subset-sum.

2. **Agentic Tool Suite (`src/tools.py`)**:
   - `check_fee_schedule`: Verifies payment gateway fee math (2% + 18% GST).
   - `find_similar_reference_ids`: Calculates Levenshtein string edit distances for typos.
   - `get_settlement_window`: Verifies T+1 to T+3 payment timing windows.
   - `sum_candidate_subsets`: Checks subset sum combinations for candidate orders.

3. **ReAct Reasoning Agent (`src/llm_agent.py`)**:
   - Executes multi-turn tool calling up to 4 iterations per candidate.
   - Retries API calls with exponential backoff (max 3 retries, timeout 15s).
   - Fallback local execution loop ensures 100% offline reliability.

4. **Human Review Queue (`src/review.py`)**:
   - Low-confidence decisions (<70%) are held in an interactive review queue.
   - Calculates human agreement rate (% approved without override) as an independent calibration signal.

5. **Calibration Engine (`src/calibration.py`)**:
   - Evaluates agent predictions in confidence buckets (0-50, 50-70, 70-90, 90-100) against hidden ground truth labels.
   - Diagnoses whether the model is Well-Calibrated, Overconfident, or Underconfident.
