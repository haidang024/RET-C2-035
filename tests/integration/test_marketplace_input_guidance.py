import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


def test_invalid_marketplace_request_returns_readable_guidance():
    graph = Graph(config={})
    graph.compile()
    result = graph.invoke(
        "Hello",
        ctx=InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL),
        input_context={"conversation_history": []},
    )
    assert result["status"] == "success"
    assert result["output"].startswith("Food-loss alert request could not be processed.")
    assert "too short" in result["output"]


def test_success_marketplace_output_is_readable_but_api_stays_json():
    graph = Graph(config={})
    report_output = json.dumps(
        {
            "report_date": "2026-08-26",
            "store_id": "STORE-01",
            "store_name": "Central Store",
            "summary": {
                "total_skus_scanned": 120,
                "alert_count": 1,
                "high_severity_count": 1,
                "estimated_loss_risk_jpy": 3500,
            },
            "alerts": [
                {
                    "sku_id": "SKU-9",
                    "name": "Fresh Bento",
                    "days_until_expiry": 1,
                    "severity": "HIGH",
                }
            ],
            "markdown_recommendations": [{"sku_id": "SKU-9", "markdown_pct": 20, "tier": "urgent"}],
            "regulatory_note": "Retain compliance data for three years.",
        }
    )
    state = {"result": report_output, "report_output": report_output, "output_valid": True}
    api_result = graph.get_output(state)
    marketplace_result = graph.get_output({**state, "input_context": {"conversation_history": []}})
    assert api_result["output"] == report_output
    assert marketplace_result["output"].startswith("# Daily Food-Loss Risk Report")
    assert "SKU-9: Fresh Bento" in marketplace_result["output"]
    assert not marketplace_result["output"].lstrip().startswith("{")
