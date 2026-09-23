"""RET-C2-035 outer post-process node."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import provider_metadata, request_advisory


# Harness H0/H6: failures the caller can correct on the next attempt.
#
# These are reported with status=success so the reason actually reaches the
# caller — the Marketplace runner discards `output` for any other status.
# INVALID_OUTPUT is deliberately absent: it means the pipeline produced an
# unusable report despite valid input, which nobody can fix from the chat box,
# so it stays status=error and trips monitoring.
_CALLER_FIXABLE_ERROR_CODES: frozenset[str] = frozenset(
    {"EMPTY_INPUT", "PARSE_ERROR", "VALIDATION_ERROR", "PII_DETECTED"}
)

_CALLER_GUIDANCE: dict[str, str] = {
    "EMPTY_INPUT": "Provide inventory data with at least one SKU row.",
    "PARSE_ERROR": (
        "Provide the inventory as JSON (a list of SKU objects) or as CSV with a header row "
        "and at least one data row."
    ),
    "VALIDATION_ERROR": "Correct the highlighted SKU fields and submit the inventory again.",
    "PII_DETECTED": ("Remove personal data (customer or staff identifiers) from the inventory before resubmitting."),
}


def _caller_message(code: str, detail: str) -> str:
    """Build a caller-safe message. Never includes node names or tracebacks."""
    # detail comes from the inner graph's own error_message field, which is
    # authored text (not a framework traceback), but keep only its first line
    # so an unexpected multi-line value can never leak internals.
    first_line = detail.splitlines()[0].strip() if detail else ""
    guidance = _CALLER_GUIDANCE.get(code, "Correct the request and try again.")
    return (
        "Food-loss alert request could not be processed.\n\n"
        f"Reason: {first_line}\n\n"
        f"How to continue:\n- {guidance}\n"
        f"Reference: {code}"
    )


class PostProcessNode(FunctionNode):
    """Finalize status and result fields after domain workflow execution."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: object | None = None, config: dict | None = None) -> None:
        super().__init__()
        self._llm = llm
        self._config = config or {}

    def execute(self, state: AgentState) -> dict:
        if state.get("input_error_message"):
            message = str(state["input_error_message"])
            return {
                "status": AgentStatus.SUCCESS.value,
                "result": message,
                "formatted_output": message,
                "input_error_message": message,
            }
        request_advisory(
            state,
            "Review the RET-C2-035 result for clarity, grounding, and safe human review.",
            self._llm,
            timeout_s=float(self._config.get("timeout_s", 30.0)),
            max_retry=int(self._config.get("max_retry", 3)),
        )
        metadata = provider_metadata(state)
        error_code = state.get("error_code")
        output_valid = bool(state.get("output_valid"))
        report_output = str(state.get("report_output", "") or "")

        if error_code or not output_valid or not report_output:
            code = str(error_code or "INVALID_OUTPUT")
            detail = str(state.get("error_message") or "The report could not be produced.")
            # Harness H6/G3: classify by *who can fix it*, not by severity.
            # The Marketplace runner drops `output` for any status != success
            # (shared/bootstrap/marketplace_app.py), so returning error here for a
            # caller-fixable problem (malformed inventory input) gives the caller a
            # bare RuntimeError and no way to learn what to correct. Report those
            # as success carrying the reason; keep error for infrastructure faults
            # so monitoring still alerts.
            if code in _CALLER_FIXABLE_ERROR_CODES:
                message = _caller_message(code, detail)
                return {
                    "status": AgentStatus.SUCCESS.value,
                    "result": message,
                    "formatted_output": message,
                    "error_code": code,
                    "error_message": detail,
                    **metadata,
                }
            return {
                "status": AgentStatus.ERROR.value,
                "result": "",
                "error_code": code,
                "error_message": detail,
                **metadata,
            }

        # S-4: chỉ log số liệu tổng hợp, không log nội dung báo cáo.
        emit_trace_event(
            "post_process_complete",
            {"report_chars": len(report_output)},
            state,
        )

        return {
            "status": AgentStatus.SUCCESS.value,
            "result": report_output,
            "error_code": None,
            "error_message": None,
            **metadata,
        }
