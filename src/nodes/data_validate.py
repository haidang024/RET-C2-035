"""DataValidateNode — validates normalized SKU records."""

from __future__ import annotations

import json
import re
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DataValidateNode(FunctionNode):
    """Validate each SKU record in inventory_items and report errors.

    Security gates:
      S-4: emit_trace_event() — audit log on entry and exit
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict) -> dict:
        # S-4: Emit trace event on entry
        emit_trace_event(
            "DataValidateNode_execute_start",
            {
                "node": "DataValidateNode",
            },
            state,
        )

        if state.get("error_code"):
            emit_trace_event(
                "DataValidateNode_skipped", {"node": "DataValidateNode", "reason": "error_propagation"}, state
            )
            return {}

        inventory_json: str | None = state.get("inventory_items")
        if not inventory_json:
            emit_trace_event(
                "DataValidateNode_error", {"node": "DataValidateNode", "error_code": "VALIDATION_ERROR"}, state
            )
            return {
                "error_code": "VALIDATION_ERROR",
                "error_message": "inventory_items is missing.",
                "validation_passed": False,
                "validation_errors": json.dumps(["inventory_items is missing."]),
            }

        try:
            items = json.loads(inventory_json)
        except Exception as exc:  # noqa: BLE001
            emit_trace_event(
                "DataValidateNode_error", {"node": "DataValidateNode", "error_code": "VALIDATION_ERROR"}, state
            )
            return {
                "error_code": "VALIDATION_ERROR",
                "error_message": f"inventory_items is not valid JSON: {exc}",
                "validation_passed": False,
                "validation_errors": json.dumps([f"inventory_items JSON parse error: {exc}"]),
            }

        errors: list[str] = []
        required_fields = {"sku_id", "name", "quantity", "expiry_date", "price", "velocity", "category"}

        for idx, item in enumerate(items):
            prefix = f"SKU[{idx}]"

            missing = required_fields - set(item.keys())
            if missing:
                errors.append(f"{prefix}: missing fields {sorted(missing)}")
                continue  # Skip further checks on incomplete record

            sku_id = item.get("sku_id", "")

            # quantity
            try:
                qty = int(item["quantity"])
                if qty < 0:
                    errors.append(f"{prefix} ({sku_id}): quantity must be >= 0, got {qty}")
            except (TypeError, ValueError):
                errors.append(f"{prefix} ({sku_id}): quantity is not a valid integer")

            # expiry_date
            expiry = str(item.get("expiry_date", ""))
            if not _ISO8601_RE.match(expiry):
                errors.append(f"{prefix} ({sku_id}): expiry_date '{expiry}' is not valid ISO8601 (YYYY-MM-DD)")

            # velocity
            try:
                vel = float(item["velocity"])
                if vel < 0:
                    errors.append(f"{prefix} ({sku_id}): velocity must be >= 0, got {vel}")
            except (TypeError, ValueError):
                errors.append(f"{prefix} ({sku_id}): velocity is not a valid number")

        if errors:
            emit_trace_event(
                "DataValidateNode_validation_failed",
                {
                    "node": "DataValidateNode",
                    "error_count": len(errors),
                },
                state,
            )
            return {
                "validation_passed": False,
                "validation_errors": json.dumps(errors, ensure_ascii=False),
                "error_code": "VALIDATION_ERROR",
                "error_message": f"Validation failed with {len(errors)} error(s).",
            }

        # S-4: Emit trace event on success
        emit_trace_event(
            "DataValidateNode_execute_complete",
            {
                "node": "DataValidateNode",
                "sku_count": len(items),
                "validation_passed": True,
            },
            state,
        )

        return {
            "validation_passed": True,
            "validation_errors": json.dumps([]),
        }
