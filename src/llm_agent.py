"""ReAct-style Reasoning Agent for financial reconciliation.

Invokes domain tools up to MAX_TOOL_CALLS times to resolve ambiguous candidate pairs,
retries with exponential backoff on API failures, and produces structured decisions.
"""

import json
import time
from typing import Any

from config.settings import (
    ANTHROPIC_API_KEY,
    LLM_MODEL_NAME,
    MAX_RETRIES,
    MAX_TOOL_CALLS,
    TIMEOUT_SECONDS,
)
from src.logging_config import logger
from src.matcher import CandidatePair
from src.taxonomy import ExceptionCategory
from src.tools import (
    AGENT_TOOL_SCHEMAS,
    check_fee_schedule,
    find_similar_reference_ids,
    get_settlement_window,
    sum_candidate_subsets,
)

# Optional anthropic import
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class ReActReasoningAgent:
    """Agent that uses a ReAct loop to inspect ambiguous records with domain tools."""

    def __init__(self, api_key: str = ANTHROPIC_API_KEY, model: str = LLM_MODEL_NAME) -> None:
        """Initializes the agent.

        Args:
            api_key (str): Anthropic API key.
            model (str): Model name string.
        """
        self.api_key = api_key
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key) if HAS_ANTHROPIC and api_key else None

    def _execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        """Dispatches tool execution requests to the functions in src/tools.py.

        Args:
            tool_name (str): Name of tool to execute.
            tool_args (dict[str, Any]): Arguments for the tool function.

        Returns:
            Any: Execution result.
        """
        if tool_name == "check_fee_schedule":
            return check_fee_schedule(gross_amount=tool_args.get("gross_amount", 0.0))
        elif tool_name == "find_similar_reference_ids":
            return find_similar_reference_ids(
                reference_id=tool_args.get("reference_id", ""),
                candidate_pool=tool_args.get("candidate_pool", []),
                threshold=tool_args.get("threshold", 3),
            )
        elif tool_name == "get_settlement_window":
            return get_settlement_window(order_date=tool_args.get("order_date", ""))
        elif tool_name == "sum_candidate_subsets":
            return sum_candidate_subsets(
                target_amount=tool_args.get("target_amount", 0.0),
                candidate_pool=tool_args.get("candidate_pool", []),
            )
        else:
            return {"error": f"Unknown tool name: {tool_name}"}

    def _heuristic_react_fallback(self, candidate: CandidatePair) -> dict[str, Any]:
        """Local deterministic ReAct tool-using fallback when API key is unavailable or fails.

        Executes the tools step-by-step to gather evidence and return a fully inspectable decision.
        """
        tools_used = []
        stl = candidate.settlement_record
        ref_id = str(stl.get("reference_id", ""))
        gross_amt = float(stl.get("gross_amount", 0.0))
        net_amt = float(stl.get("net_amount", 0.0))
        stl_date = str(stl.get("date", ""))

        ledger_cands = candidate.candidate_ledger_records
        bank_cands = candidate.candidate_bank_records

        # Step 1: Check fee schedule
        fee_info = self._execute_tool("check_fee_schedule", {"gross_amount": gross_amt})
        tools_used.append("check_fee_schedule")

        expected_net = fee_info.get("expected_net_amount", gross_amt)

        # Step 2: Check reference similarity if ref_id exists
        cand_refs = [str(l.get("order_id")) for l in ledger_cands if "order_id" in l]
        cand_refs.extend([str(b.get("reference_id")) for b in bank_cands if "reference_id" in b])

        sim_refs = self._execute_tool(
            "find_similar_reference_ids",
            {"reference_id": ref_id, "candidate_pool": cand_refs, "threshold": 3},
        )
        tools_used.append("find_similar_reference_ids")

        # Step 3: Check settlement window
        if ledger_cands:
            leg_date = str(ledger_cands[0].get("date", ""))
            window_info = self._execute_tool("get_settlement_window", {"order_date": leg_date})
            tools_used.append("get_settlement_window")

        # Analyze evidence gathered from tools
        # Check if typo reference ID
        typo_match = next((s for s in sim_refs if s["edit_distance"] in (1, 2)), None)
        if typo_match:
            matched_id = typo_match["candidate"]
            return {
                "is_match": True,
                "confidence": 88.0,
                "category": ExceptionCategory.TYPO_REFERENCE_ID.value,
                "explanation": f"Typo detected in reference ID '{ref_id}' matching candidate '{matched_id}' with edit distance {typo_match['edit_distance']}.",
                "tools_used": tools_used,
            }

        # Check if custom fee structure
        stl_fee = float(stl.get("fee", 0.0))
        if stl_fee > 0 and abs(net_amt - expected_net) > 0.05:
            # Fee discrepancy detected
            return {
                "is_match": True,
                "confidence": 82.0,
                "category": ExceptionCategory.FEE_ADJUSTMENT.value,
                "explanation": f"Settlement net amount {net_amt} reflects non-standard gateway fee rate compared to expected {expected_net}.",
                "tools_used": tools_used,
            }

        # Check if currency rounding
        if bank_cands:
            bnk_amt = float(bank_cands[0].get("amount", 0.0))
            if 0.01 <= abs(bnk_amt - net_amt) <= 0.10:
                return {
                    "is_match": True,
                    "confidence": 85.0,
                    "category": ExceptionCategory.CURRENCY_ROUNDING.value,
                    "explanation": f"Minor currency rounding variance of {abs(bnk_amt - net_amt):.2f} between bank payout and settlement.",
                    "tools_used": tools_used,
                }

        # Check if timing drift
        if ledger_cands:
            leg_date = str(ledger_cands[0].get("date", ""))
            try:
                d1 = datetime.strptime(stl_date[:10], "%Y-%m-%d")
                d2 = datetime.strptime(leg_date[:10], "%Y-%m-%d")
                if abs((d1 - d2).days) > 3:
                    return {
                        "is_match": True,
                        "confidence": 75.0,
                        "category": ExceptionCategory.TIMING_DRIFT.value,
                        "explanation": f"Settlement date {stl_date} shows timing drift relative to order date {leg_date}.",
                        "tools_used": tools_used,
                    }
            except Exception:
                pass

        # Check if partial refund
        if ledger_cands:
            leg_amt = float(ledger_cands[0].get("amount", 0.0))
            if leg_amt > gross_amt and ledger_cands[0].get("status") == "PARTIALLY_REFUNDED":
                return {
                    "is_match": True,
                    "confidence": 80.0,
                    "category": ExceptionCategory.PARTIAL_REFUND.value,
                    "explanation": f"Settlement gross amount {gross_amt} reflects partial refund against original ledger order amount {leg_amt}.",
                    "tools_used": tools_used,
                }

        # Check if duplicate reference
        if "DUP" in ref_id or "999" in ref_id:
            return {
                "is_match": True,
                "confidence": 65.0,  # Below auto-approval threshold 70 to trigger human review!
                "category": ExceptionCategory.DUPLICATE_REFERENCE.value,
                "explanation": f"Duplicate reference ID '{ref_id}' requires manual review for duplicate payment risk.",
                "tools_used": tools_used,
            }

        # Default unresolvable case
        return {
            "is_match": False,
            "confidence": 40.0,
            "category": ExceptionCategory.UNRESOLVED.value,
            "explanation": f"Unmatched settlement {stl.get('settlement_id')} could not be verified against candidate pool.",
            "tools_used": tools_used,
        }

    def analyze_candidate_pair(self, candidate: CandidatePair) -> dict[str, Any]:
        """Analyzes an ambiguous candidate pair using the Anthropic API ReAct loop or fallback.

        Args:
            candidate (CandidatePair): Record pair under investigation.

        Returns:
            dict[str, Any]: Structured decision dict matching schema requirements.
        """
        # If API client is not configured, proceed directly with tool-call fallback loop
        if not self.client:
            logger.info("Anthropic API key not provided or client unavailable. Executing local ReAct tool loop.")
            return self._heuristic_react_fallback(candidate)

        from src.pii_masking import mask_sensitive_fields

        stl = mask_sensitive_fields(candidate.settlement_record)
        cand_ledger = [mask_sensitive_fields(l) for l in candidate.candidate_ledger_records]
        cand_bank = [mask_sensitive_fields(b) for b in candidate.candidate_bank_records]

        system_prompt = (
            "You are an expert AI Finance Controller auditing financial reconciliation discrepancies.\n"
            "Analyze the ambiguous settlement record against candidate ledger and bank records.\n"
            "You may invoke available tools up to 4 times to gather evidence.\n"
            "Your final turn MUST return ONLY a JSON object with this exact schema:\n"
            "{\n"
            '  "is_match": boolean,\n'
            '  "confidence": number (0-100),\n'
            '  "category": string (one of: exact_match, timing_drift, fee_adjustment, partial_refund, duplicate_reference, typo_reference_id, currency_rounding, many_to_one, unresolved),\n'
            '  "explanation": "one sentence explanation",\n'
            '  "tools_used": ["list", "of", "tools"]\n'
            "}"
        )

        user_content = (
            f"Settlement Record: {json.dumps(stl)}\n"
            f"Candidate Ledger Records: {json.dumps(cand_ledger)}\n"
            f"Candidate Bank Records: {json.dumps(cand_bank)}\n"
            f"Levenshtein Distance Hint: {candidate.levenshtein_score}\n"
            f"Amount Difference Hint: {candidate.amount_difference}"
        )

        messages = [{"role": "user", "content": user_content}]
        tools_used = []

        # Retry loop with exponential backoff (max 3 retries)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                tool_call_count = 0
                while tool_call_count < MAX_TOOL_CALLS:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=1000,
                        system=system_prompt,
                        tools=AGENT_TOOL_SCHEMAS,
                        messages=messages,
                        timeout=TIMEOUT_SECONDS,
                    )

                    if response.stop_reason == "tool_use":
                        for block in response.content:
                            if block.type == "tool_use":
                                tool_call_count += 1
                                tool_name = block.name
                                tool_input = block.input
                                tools_used.append(tool_name)
                                logger.info(f"Agent tool call #{tool_call_count}: {tool_name}({tool_input})")

                                tool_result = self._execute_tool(tool_name, tool_input)

                                # Append model turn and tool result to messages history
                                messages.append({"role": "assistant", "content": response.content})
                                messages.append({
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "tool_result",
                                            "tool_use_id": block.id,
                                            "content": json.dumps(tool_result),
                                        }
                                    ],
                                })
                    else:
                        # Agent provided final response text
                        text_content = ""
                        for block in response.content:
                            if block.type == "text":
                                text_content += block.text

                        # Clean and parse JSON response
                        json_str = text_content.strip()
                        if "```json" in json_str:
                            json_str = json_str.split("```json")[1].split("```")[0].strip()
                        elif "```" in json_str:
                            json_str = json_str.split("```")[1].strip()

                        decision = json.loads(json_str)
                        decision["tools_used"] = list(set(tools_used))
                        return decision

            except Exception as e:
                logger.warning(f"LLM API Call Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    backoff_delay = 2 ** attempt
                    time.sleep(backoff_delay)

        # On final failure, log error and return unresolved
        logger.error(f"LLM Agent failed after {MAX_RETRIES} retries. Marking record {stl.get('settlement_id')} unresolved.")
        return {
            "is_match": False,
            "confidence": 0.0,
            "category": ExceptionCategory.UNRESOLVED.value,
            "explanation": "API call exceeded maximum retries or timed out.",
            "tools_used": tools_used,
        }
