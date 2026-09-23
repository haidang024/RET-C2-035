"""InputParseNode — parses raw CSV/JSON inventory input into normalized SKU records."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from typing import Any, ClassVar, Dict

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# S-2: PII patterns to detect in raw input
_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{4}-\d{4}\b"),  # JP phone number
    re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"),  # credit card
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),  # email
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-like
    re.compile(r"(?i)(password|passwd|secret|api[_\-]?key)\s*[=:]\s*\S+"),  # credentials
]


class InputParseNode(FunctionNode):
    """Parse raw inventory input (CSV or JSON) into a normalized list of SKU dicts.

      Security gates:
          S-1: required_trust_level declared (VERIFIED_EXTERNAL)
    S-2: _extra_security_gate_input() — PII pattern scan on raw_input
    S-4: emit_trace_event() — audit log on entry and exit
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict) -> dict:
        state = {**state, **self._extract_payload(state)}
        # S-4: Emit trace event on entry
        emit_trace_event(
            "InputParseNode_execute_start",
            {
                "node": "InputParseNode",
                "store_id": self._safe_store_id(state),
                "raw_input_bytes": len(state.get("raw_input") or ""),
            },
            state,
        )

        # Skip if a prior node already signalled an error
        if state.get("error_code"):
            emit_trace_event("InputParseNode_skipped", {"node": "InputParseNode", "reason": "error_propagation"}, state)
            return {}

        raw_input: str | None = state.get("raw_input")
        store_context: str | None = state.get("store_context")

        # ── Empty-input guard ────────────────────────────────────────────────
        if not raw_input or not raw_input.strip():
            emit_trace_event("InputParseNode_error", {"node": "InputParseNode", "error_code": "EMPTY_INPUT"}, state)
            return {
                "error_code": "EMPTY_INPUT",
                "error_message": "raw_input is empty or missing.",
            }

        # ── S-2: PII detection gate on raw_input ─────────────────────────────
        pii_result = self._extra_security_gate_input(state)
        if pii_result is not None and isinstance(pii_result, dict) and pii_result.get("error_code"):
            emit_trace_event("InputParseNode_error", {"node": "InputParseNode", "error_code": "PII_DETECTED"}, state)
            return pii_result

        # ── Detect and parse format ──────────────────────────────────────────
        stripped = raw_input.strip()
        try:
            if stripped.startswith("[") or stripped.startswith("{"):
                items = self._parse_json(stripped)
            else:
                items = self._parse_csv(stripped)
        except Exception as exc:  # noqa: BLE001
            emit_trace_event("InputParseNode_error", {"node": "InputParseNode", "error_code": "PARSE_ERROR"}, state)
            return {
                "error_code": "PARSE_ERROR",
                "error_message": f"Failed to parse input: {exc}",
            }

        # ── Resolve report_format from store_context (falls back to "json") ──
        report_format = "json"
        if store_context:
            try:
                ctx = json.loads(store_context)
                report_format = ctx.get("report_format", "json")
            except Exception:  # noqa: BLE001
                pass

        processing_date = date.today().isoformat()

        result = {
            "raw_input": raw_input,
            "store_context": store_context or "{}",
            "inventory_items": json.dumps(items, ensure_ascii=False),
            "processing_date": processing_date,
            "report_format": report_format,
        }

        # S-4: Emit trace event on success
        emit_trace_event(
            "InputParseNode_execute_complete",
            {
                "node": "InputParseNode",
                "store_id": self._safe_store_id(state),
                "sku_count": len(items),
                "report_format": report_format,
                "processing_date": processing_date,
            },
            state,
        )

        return result

    # ── S-2: PII detection hook ───────────────────────────────────────────────

    def _extra_security_gate_input(self, state: dict) -> dict:
        """Scan raw_input for PII patterns and return framework state.

        NOTE: raw_input byte length is logged in trace events, never the content itself.
        """
        state = {**state, **self._extract_payload(state)}
        raw_input = state.get("raw_input", "") or ""
        # Truncate at 1 MB before scanning (also enforced here as a safety ceiling)
        scan_target = raw_input[:1_048_576]
        for pattern in _PII_PATTERNS:
            if pattern.search(scan_target):
                description = f"matched pattern: {pattern.pattern[:40]}..."
                return {
                    **state,
                    "error_code": "PII_DETECTED",
                    "error_message": f"PII detected in raw_input: {description}. Input rejected.",
                }
        return state

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_payload(state: dict) -> dict:
        user_input = state.get("user_input")
        if isinstance(user_input, str) and user_input.strip():
            try:
                decoded = json.loads(user_input)
            except json.JSONDecodeError:
                return {}
            if isinstance(decoded, dict) and "raw_input" in decoded:
                return decoded
        return {}

    def _parse_json(self, raw: str) -> list:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError("JSON input must be an array (or a single object).")
        return [self._normalize(item) for item in data]

    def _parse_csv(self, raw: str) -> list:
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            raise ValueError("CSV input has no data rows.")
        return [self._normalize(row) for row in rows]

    @staticmethod
    def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "sku_id": str(item.get("sku_id", "")),
            "name": str(item.get("name", "")),
            "quantity": int(float(item.get("quantity", 0))),
            "expiry_date": str(item.get("expiry_date", "")),
            "price": float(item.get("price", 0.0)),
            "velocity": float(item.get("velocity", 0.0)),
            "category": str(item.get("category", "")),
        }

    @staticmethod
    def _safe_store_id(state: Any) -> str:
        """Extract store_id from store_context for safe audit logging."""
        try:
            ctx = json.loads(state.get("store_context") or "{}")
            return str(ctx.get("store_id", "unknown"))
        except Exception:  # noqa: BLE001
            return "unknown"
