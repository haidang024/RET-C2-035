"""RET-C2-035 outer pre-process node."""

from __future__ import annotations

import json
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

MIN_RAW_INPUT_CHARS = 10

_INPUT_GUIDANCE = [
    "Provide raw inventory data directly, or a JSON object with raw_input and optional store_context.",
    "store_context must be a JSON object or JSON string; report_format may be json or markdown.",
    "Include enough SKU, quantity, expiry, and store context to generate a food-loss alert.",
]


def _input_error(message: str) -> dict:
    return {
        "status": AgentStatus.SUCCESS.value,
        "input_error_message": message,
        "input_error_guidance": _INPUT_GUIDANCE,
        "error_code": None,
        "error_message": None,
    }


class PreProcessNode(FunctionNode):
    """Validate input envelope before entering the domain workflow."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: AgentState) -> dict:
        raw_input, store_context = self._extract_request(state)
        if not isinstance(raw_input, str) or not raw_input.strip():
            return _input_error("Please provide inventory data in raw_input.")

        if len(raw_input.strip()) < MIN_RAW_INPUT_CHARS:
            return _input_error("The inventory input is too short to identify any SKU or expiry information.")

        if isinstance(store_context, dict):
            store_context = json.dumps(store_context, ensure_ascii=False)
        if not isinstance(store_context, str):
            return _input_error("store_context must be a JSON string or object.")

        report_format = "json"
        try:
            ctx = json.loads(store_context or "{}")
            report_format = str(ctx.get("report_format", "json")).lower()
        except (json.JSONDecodeError, TypeError):
            return _input_error("store_context is not valid JSON.")

        if report_format not in {"json", "markdown"}:
            return _input_error("report_format must be json or markdown.")

        # S-4: chỉ log tham số đã chuẩn hoá, không log nội dung inventory.
        emit_trace_event(
            "pre_process_validated",
            {"report_format": report_format, "input_chars": len(raw_input.strip())},
            state,
        )

        return {
            "validated_input": raw_input.strip(),
            "raw_input": raw_input.strip(),
            "store_context": store_context,
            "report_format": report_format,
            "status": AgentStatus.SUCCESS.value,
            "error_code": None,
            "error_message": None,
        }

    def _extract_request(self, state: AgentState) -> tuple[object, object]:
        raw_input: object = state.get("raw_input", state.get("user_input", ""))
        store_context: object = state.get("store_context", "{}")
        user_input = state.get("user_input")
        if not isinstance(user_input, str) or not user_input.strip():
            return raw_input, store_context
        try:
            decoded = json.loads(user_input)
        except json.JSONDecodeError:
            return raw_input, store_context
        if isinstance(decoded, dict) and "raw_input" in decoded:
            raw_input = decoded.get("raw_input", "")
            store_context = decoded.get("store_context", store_context)
        return raw_input, store_context
