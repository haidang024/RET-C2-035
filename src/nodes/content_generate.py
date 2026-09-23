"""ContentGenerateNode — generates SKU alerts and markdown-down recommendations."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_DEFAULT_EXPIRY_ALERT_DAYS = 3
_DEFAULT_TIERS = {
    "TIER_1": {"days_threshold": 1, "markdown_pct": 50.0},
    "TIER_2": {"days_threshold": 2, "markdown_pct": 30.0},
    "TIER_3": {"days_threshold": 3, "markdown_pct": 15.0},
}


class ContentGenerateNode(FunctionNode):
    """Generate near-expiry alerts and markdown price recommendations.

    Security gates:
      S-4: emit_trace_event() — audit log on entry and exit
          NOTE: raw inventory content is NEVER logged — only sku_count and alert_count.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def execute(self, state: dict) -> dict:
        # S-4: Emit trace event on entry
        emit_trace_event(
            "ContentGenerateNode_execute_start",
            {
                "node": "ContentGenerateNode",
            },
            state,
        )

        if state.get("error_code"):
            emit_trace_event(
                "ContentGenerateNode_skipped", {"node": "ContentGenerateNode", "reason": "error_propagation"}, state
            )
            return {}

        if not state.get("validation_passed"):
            emit_trace_event(
                "ContentGenerateNode_skipped", {"node": "ContentGenerateNode", "reason": "validation_not_passed"}, state
            )
            return {}

        inventory_json: str | None = state.get("inventory_items")
        if not inventory_json:
            return {}

        items = json.loads(inventory_json)

        # ── Config resolution ────────────────────────────────────────────────
        expiry_alert_days = _DEFAULT_EXPIRY_ALERT_DAYS
        tiers = _DEFAULT_TIERS

        expiry_alert_days = int(self.config.get("expiry_alert_days", expiry_alert_days))
        configured_tiers = self.config.get("markdown_tiers")
        if isinstance(configured_tiers, dict) and configured_tiers:
            tiers = configured_tiers

        # ── Processing date ──────────────────────────────────────────────────
        processing_date_str: str = state.get("processing_date") or date.today().isoformat()
        try:
            processing_date = date.fromisoformat(processing_date_str)
        except ValueError:
            processing_date = date.today()

        sku_alerts: list[dict] = []
        markdown_recommendations: list[dict] = []

        for item in items:
            expiry_str = str(item.get("expiry_date", ""))
            try:
                expiry_date = date.fromisoformat(expiry_str)
            except ValueError:
                continue  # Skip unparseable dates

            days_until_expiry = (expiry_date - processing_date).days

            if days_until_expiry > expiry_alert_days:
                continue  # Not near expiry

            # Severity
            if days_until_expiry <= 1:
                severity = "HIGH"
            elif days_until_expiry <= 2:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            sku_alerts.append(
                {
                    "sku_id": item["sku_id"],
                    "name": item["name"],
                    "expiry_date": expiry_str,
                    "days_until_expiry": days_until_expiry,
                    "quantity": item["quantity"],
                    "severity": severity,
                }
            )

            # Tier selection
            tier_name, markdown_pct = self._select_tier(days_until_expiry, tiers)
            current_price = float(item.get("price", 0.0))
            recommended_price = round(current_price * (1 - markdown_pct / 100), 1)

            markdown_recommendations.append(
                {
                    "sku_id": item["sku_id"],
                    "name": item["name"],
                    "current_price": current_price,
                    "recommended_price": recommended_price,
                    "markdown_pct": markdown_pct,
                    "tier": tier_name,
                }
            )

        # S-4: Emit trace event on success — NOTE: counts only, never content
        emit_trace_event(
            "ContentGenerateNode_execute_complete",
            {
                "node": "ContentGenerateNode",
                "sku_count": len(items),
                "alert_count": len(sku_alerts),
                "expiry_alert_days": expiry_alert_days,
            },
            state,
        )

        return {
            "sku_alerts": json.dumps(sku_alerts, ensure_ascii=False),
            "markdown_recommendations": json.dumps(markdown_recommendations, ensure_ascii=False),
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _select_tier(days_until_expiry: int, tiers: dict) -> tuple[str, float]:
        """Return (tier_name, markdown_pct) for the tightest matching tier."""
        # Sort tiers by ascending days_threshold so we pick the tightest match first
        sorted_tiers = sorted(
            tiers.items(),
            key=lambda kv: int(kv[1].get("days_threshold", 99)),
        )
        for tier_name, tier_cfg in sorted_tiers:
            if days_until_expiry <= int(tier_cfg.get("days_threshold", 99)):
                return tier_name, float(tier_cfg.get("markdown_pct", 0.0))
        # Fallback: lowest markdown
        last_name, last_cfg = sorted_tiers[-1]
        return last_name, float(last_cfg.get("markdown_pct", 0.0))
