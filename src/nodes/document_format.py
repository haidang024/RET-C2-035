"""DocumentFormatNode — assembles the final daily food-loss risk report."""

from __future__ import annotations

import json
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class DocumentFormatNode(FunctionNode):
    """Build and format the daily food-loss risk report (JSON or Markdown).

    Security gates:
      S-4: emit_trace_event() — audit log on entry and exit
          NOTE: report content is NOT logged — only store_id, report_format, alert_count.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict) -> dict:
        # S-4: Emit trace event on entry
        emit_trace_event(
            "DocumentFormatNode_execute_start",
            {
                "node": "DocumentFormatNode",
                "report_format": state.get("report_format", "json"),
            },
            state,
        )

        if state.get("error_code"):
            emit_trace_event(
                "DocumentFormatNode_skipped", {"node": "DocumentFormatNode", "reason": "error_propagation"}, state
            )
            return {}

        # ── Gather state fields ──────────────────────────────────────────────
        sku_alerts_json: str | None = state.get("sku_alerts")
        recos_json: str | None = state.get("markdown_recommendations")
        store_ctx_json: str | None = state.get("store_context")
        inventory_json: str | None = state.get("inventory_items")
        processing_date: str = state.get("processing_date", "")
        report_format: str = state.get("report_format", "json")

        sku_alerts = json.loads(sku_alerts_json) if sku_alerts_json else []
        recommendations = json.loads(recos_json) if recos_json else []
        inventory_items = json.loads(inventory_json) if inventory_json else []

        store_id = ""
        store_name = ""
        if store_ctx_json:
            try:
                ctx = json.loads(store_ctx_json)
                store_id = ctx.get("store_id", "")
                store_name = ctx.get("store_name", "")
                if not processing_date:
                    processing_date = ctx.get("report_date", "")
            except Exception:  # noqa: BLE001
                pass

        # ── Summary computation ──────────────────────────────────────────────
        total_skus_scanned = len(inventory_items)
        alert_count = len(sku_alerts)
        high_severity_count = sum(1 for a in sku_alerts if a.get("severity") == "HIGH")

        # Build quick-lookup from inventory for price
        price_lookup = {item["sku_id"]: float(item.get("price", 0.0)) for item in inventory_items}
        estimated_loss_risk_jpy = sum(
            int(a.get("quantity", 0)) * price_lookup.get(a["sku_id"], 0.0) for a in sku_alerts
        )

        # ── Report dict ─────────────────────────────────────────────────────
        report: dict = {
            "report_date": processing_date,
            "store_id": store_id,
            "store_name": store_name,
            "summary": {
                "total_skus_scanned": total_skus_scanned,
                "alert_count": alert_count,
                "high_severity_count": high_severity_count,
                "estimated_loss_risk_jpy": round(estimated_loss_risk_jpy, 2),
            },
            "alerts": sku_alerts,
            "markdown_recommendations": recommendations,
            "regulatory_note": ("食品ロス削減推進法 compliance data — retain for 3 years"),
        }

        # ── Format ───────────────────────────────────────────────────────────
        if report_format == "markdown":
            report_output = self._render_markdown(report)
        else:
            report_output = json.dumps(report, ensure_ascii=False, indent=2)

        # S-4: Emit trace event on success — NOTE: content not logged, metadata only
        emit_trace_event(
            "DocumentFormatNode_execute_complete",
            {
                "node": "DocumentFormatNode",
                "store_id": store_id,
                "report_format": report_format,
                "alert_count": alert_count,
                "total_skus_scanned": total_skus_scanned,
                "processing_date": processing_date,
            },
            state,
        )

        return {"report_output": report_output}

    # ── Markdown renderer ─────────────────────────────────────────────────────

    @staticmethod
    def _render_markdown(report: dict) -> str:
        s = report["summary"]
        lines = [
            "# Daily Food-Loss Risk Report",
            "",
            f"**Date:** {report['report_date']}  ",
            f"**Store:** {report['store_name']} (`{report['store_id']}`)",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| SKUs scanned | {s['total_skus_scanned']} |",
            f"| Alert count  | {s['alert_count']} |",
            f"| HIGH severity | {s['high_severity_count']} |",
            f"| Est. loss risk (¥) | {s['estimated_loss_risk_jpy']:,.0f} |",
            "",
            "## Near-Expiry Alerts",
            "",
        ]

        if report["alerts"]:
            lines += [
                "| SKU ID | Name | Expiry | Days Left | Qty | Severity |",
                "|--------|------|--------|-----------|-----|----------|",
            ]
            for a in report["alerts"]:
                lines.append(
                    f"| {a['sku_id']} | {a['name']} | {a['expiry_date']} "
                    f"| {a['days_until_expiry']} | {a['quantity']} | {a['severity']} |"
                )
        else:
            lines.append("_No near-expiry SKUs detected._")

        lines += ["", "## Markdown Recommendations", ""]

        if report["markdown_recommendations"]:
            lines += [
                "| SKU ID | Name | Current ¥ | Recommended ¥ | Markdown % | Tier |",
                "|--------|------|-----------|---------------|------------|------|",
            ]
            for r in report["markdown_recommendations"]:
                lines.append(
                    f"| {r['sku_id']} | {r['name']} | {r['current_price']} "
                    f"| {r['recommended_price']} | {r['markdown_pct']} | {r['tier']} |"
                )
        else:
            lines.append("_No markdown recommendations._")

        lines += [
            "",
            f"> **Regulatory note:** {report['regulatory_note']}",
        ]

        return "\n".join(lines)
