"""Centralized configuration settings for AI Finance Controller."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if available
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# API Configuration
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "claude-3-5-sonnet-20241022")

# Pipeline & Matcher Tunables
DATE_WINDOW_DAYS: int = int(os.getenv("DATE_WINDOW_DAYS", "3"))
AMOUNT_ROUNDING_TOLERANCE: float = float(os.getenv("AMOUNT_ROUNDING_TOLERANCE", "0.05"))
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "70.0"))

# LLM Agent Constraints
MAX_RETRIES: int = 3
TIMEOUT_SECONDS: int = 15
MAX_TOOL_CALLS: int = 4

# Paths
DATA_DIR: Path = BASE_DIR / "data"
OUTPUTS_DIR: Path = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True, parents=True)

# Standard Fee Schedule for Verification (Razorpay simulated fee rules)
# Percentage fee and fixed transaction fee in INR
FEE_SCHEDULE = {
    "standard_rate": 0.02,  # 2.0% payment gateway fee
    "gst_rate": 0.18,       # 18% GST on gateway fee
    "fixed_fee": 0.0        # Optional flat fee per transaction
}
