"""RET-C2-035 unit tests for domain workflow nodes."""

from __future__ import annotations

import json

from src.nodes.content_generate import ContentGenerateNode
from src.nodes.data_validate import DataValidateNode
from src.nodes.document_format import DocumentFormatNode
from src.nodes.input_parse import InputParseNode
from src.nodes.output_validate import OutputValidateNode


def test_input_parse_json_success() -> None:
    node = InputParseNode()
    payload = json.dumps(
        [
            {
                "sku_id": "SKU-001",
                "name": "Apple",
                "quantity": 10,
                "expiry_date": "2026-06-26",
                "price": 120.0,
                "velocity": 3.0,
                "category": "produce",
            }
        ]
    )
    state = {
        "raw_input": payload,
        "store_context": json.dumps({"store_id": "S001", "report_format": "json"}),
    }

    result = node.execute(state)
    assert result.get("error_code") is None
    items = json.loads(result["inventory_items"])
    assert len(items) == 1


def test_data_validate_rejects_bad_date() -> None:
    node = DataValidateNode()
    state = {
        "inventory_items": json.dumps(
            [
                {
                    "sku_id": "SKU-001",
                    "name": "Apple",
                    "quantity": 10,
                    "expiry_date": "2026/06/26",
                    "price": 120.0,
                    "velocity": 3.0,
                    "category": "produce",
                }
            ]
        )
    }

    result = node.execute(state)
    assert result["validation_passed"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


def test_content_generate_produces_alerts() -> None:
    node = ContentGenerateNode()
    state = {
        "validation_passed": True,
        "processing_date": "2026-06-25",
        "inventory_items": json.dumps(
            [
                {
                    "sku_id": "SKU-001",
                    "name": "Apple",
                    "quantity": 10,
                    "expiry_date": "2026-06-26",
                    "price": 120.0,
                    "velocity": 3.0,
                    "category": "produce",
                }
            ]
        ),
    }

    result = node.execute(state)
    alerts = json.loads(result["sku_alerts"])
    recos = json.loads(result["markdown_recommendations"])
    assert len(alerts) == 1
    assert len(recos) == 1
    assert recos[0]["markdown_pct"] == 50.0


def test_document_format_json_output() -> None:
    node = DocumentFormatNode()
    state = {
        "inventory_items": json.dumps(
            [
                {
                    "sku_id": "SKU-001",
                    "name": "Apple",
                    "quantity": 10,
                    "expiry_date": "2026-06-26",
                    "price": 120.0,
                    "velocity": 3.0,
                    "category": "produce",
                }
            ]
        ),
        "sku_alerts": json.dumps([]),
        "markdown_recommendations": json.dumps([]),
        "store_context": json.dumps({"store_id": "S001", "store_name": "Store A"}),
        "processing_date": "2026-06-25",
        "report_format": "json",
    }

    result = node.execute(state)
    parsed = json.loads(result["report_output"])
    assert parsed["store_id"] == "S001"
    assert "summary" in parsed


def test_output_validate_flags_missing_required_json_keys() -> None:
    node = OutputValidateNode()
    state = {
        "report_format": "json",
        "report_output": json.dumps({"report_date": "2026-06-25"}),
    }

    result = node.execute(state)
    assert result["output_valid"] is False
