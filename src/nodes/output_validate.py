"""OutputValidateNode — final gate; always runs regardless of error_code."""

from __future__ import annotations

import json
import re
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_REQUIRED_JSON_KEYS = {"report_date", "store_id", "summary", "alerts", "markdown_recommendations"}

# S-3: Credential / sensitive-data patterns for output safety scan
_CREDENTIAL_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style key
    re.compile(r"eyJ[a-zA-Z0-9._\-]{10,}"),  # JWT
    re.compile(r"AKIA[A-Z0-9]{16}"),  # AWS access key
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{20,}"),  # Bearer token
    re.compile(r"(?i)(password|passwd|secret|api[_\-]?key)\s*[=:]\s*\S{8,}"),  # KV secrets
]


class OutputValidateNode(FunctionNode):
    """Validate the generated report_output; always runs even when error_code is set.

    Security gates:
      S-3: _extra_security_gate_output() — credential / content safety scan on report_output
      S-4: emit_trace_event() — audit log (always fires, including error path)
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict) -> dict:
        # S-4: Always emit trace on entry — this node runs even on error path
        emit_trace_event(
            "OutputValidateNode_execute_start",
            {
                "node": "OutputValidateNode",
                "has_error_code": bool(state.get("error_code")),
                "report_format": state.get("report_format", "json"),
                "output_valid": state.get("output_valid"),
            },
            state,
        )

        # If a prior error occurred, mark output invalid and return — do NOT set error_code.
        if state.get("error_code"):
            emit_trace_event(
                "OutputValidateNode_execute_complete",
                {
                    "node": "OutputValidateNode",
                    "output_valid": False,
                    "reason": "upstream_error",
                },
                state,
            )
            return {"output_valid": False}

        report_output: str | None = state.get("report_output")
        report_format: str = state.get("report_format", "json")

        # ── Empty output ─────────────────────────────────────────────────────
        if not report_output or not report_output.strip():
            emit_trace_event(
                "OutputValidateNode_execute_complete",
                {
                    "node": "OutputValidateNode",
                    "output_valid": False,
                    "reason": "empty_output",
                },
                state,
            )
            return {"output_valid": False}

        # ── S-3: Content safety / credential leakage scan ─────────────────────
        gate_result = self._extra_security_gate_output({"report_output": report_output})
        gate_output = (
            gate_result.get("report_output", report_output) if isinstance(gate_result, dict) else report_output
        )
        if gate_output != report_output:
            # Gate blocked or modified output — treat as invalid
            emit_trace_event(
                "OutputValidateNode_s3_gate_blocked",
                {
                    "node": "OutputValidateNode",
                    "output_valid": False,
                },
                state,
            )
            return {"output_valid": False, "report_output": gate_output}

        # ── Format-specific structural validation ─────────────────────────────
        if report_format == "markdown":
            # Non-empty markdown string that passed S-3 gate is sufficient
            emit_trace_event(
                "OutputValidateNode_execute_complete",
                {
                    "node": "OutputValidateNode",
                    "output_valid": True,
                    "report_format": "markdown",
                },
                state,
            )
            return {"output_valid": True}

        # JSON format: parse and check required keys
        try:
            parsed = json.loads(report_output)
        except (json.JSONDecodeError, ValueError):
            emit_trace_event(
                "OutputValidateNode_execute_complete",
                {
                    "node": "OutputValidateNode",
                    "output_valid": False,
                    "reason": "json_parse_error",
                },
                state,
            )
            return {"output_valid": False}

        if not isinstance(parsed, dict):
            emit_trace_event(
                "OutputValidateNode_execute_complete",
                {
                    "node": "OutputValidateNode",
                    "output_valid": False,
                    "reason": "not_a_dict",
                },
                state,
            )
            return {"output_valid": False}

        missing_keys = _REQUIRED_JSON_KEYS - set(parsed.keys())
        if missing_keys:
            emit_trace_event(
                "OutputValidateNode_execute_complete",
                {
                    "node": "OutputValidateNode",
                    "output_valid": False,
                    "reason": f"missing_keys:{sorted(missing_keys)}",
                },
                state,
            )
            return {"output_valid": False}

        emit_trace_event(
            "OutputValidateNode_execute_complete",
            {
                "node": "OutputValidateNode",
                "output_valid": True,
                "report_format": "json",
            },
            state,
        )
        return {"output_valid": True}

    # ── S-3: Output safety hook ───────────────────────────────────────────────

    def _extra_security_gate_output(self, output: dict) -> dict:
        """Scan report_output for credential leakage patterns.

        Returns the original output dict if clean, or with report_output set to
        a BLOCKER string if a credential pattern is detected.
        Never logs report content itself.
        """
        report_output = output.get("report_output", "") or ""
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(report_output):
                return {
                    **output,
                    "report_output": "BLOCKER: Credential pattern detected in report output — output suppressed.",
                }
        return output
