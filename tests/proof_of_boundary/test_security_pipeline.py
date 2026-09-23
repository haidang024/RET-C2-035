"""RET-C2-035 proof-of-boundary tests for security and pipeline behavior."""

from __future__ import annotations

import json
from pathlib import Path

from datetime import date, timedelta

import yaml

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph import Graph
from src.nodes.input_parse import InputParseNode
from src.nodes.output_validate import OutputValidateNode
from src.nodes.pre_process_node import PreProcessNode


_CONFIG = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "config.yaml").read_text())


def _invoke_verified(payload: dict) -> dict:
    graph = Graph(config=dict(_CONFIG))
    ctx = InvocationContext(
        session_id="pb-security-pipeline",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
    )
    return graph.invoke(json.dumps(payload), ctx=ctx)


def test_pb_s1_empty_input_returns_guidance() -> None:
    node = PreProcessNode()
    result = node.execute({"raw_input": "", "store_context": "{}"})
    assert result["status"] == AgentStatus.SUCCESS.value
    assert result["input_error_message"]


def test_pb_s2_pii_detection_blocks_input_parse() -> None:
    node = InputParseNode()
    state = {
        "raw_input": "name,email\nJohn,john@example.com",
        "store_context": json.dumps({"store_id": "S001"}),
    }
    result = node.execute(state)
    assert result["error_code"] == "PII_DETECTED"


def test_pb_s3_output_validate_blocks_credentials() -> None:
    node = OutputValidateNode()
    state = {
        "report_format": "markdown",
        "report_output": "Leaked token sk-abcdefghijklmnopqrstuvwx",
    }
    result = node.execute(state)
    assert result["output_valid"] is False


def test_pb_graph_happy_path() -> None:
    state = {
        "raw_input": json.dumps(
            [
                {
                    "sku_id": "SKU-001",
                    "name": "Apple",
                    "quantity": 10,
                    "expiry_date": (date.today() + timedelta(days=1)).isoformat(),
                    "price": 120.0,
                    "velocity": 3.0,
                    "category": "produce",
                }
            ]
        ),
        "store_context": json.dumps({"store_id": "S001", "store_name": "Store A", "report_date": "2026-06-25"}),
    }

    result = _invoke_verified(state)
    assert result["status"] == AgentStatus.SUCCESS
    assert result["output_valid"] is True
    assert result["report_output"]


def test_pb_graph_input_error_path_returns_guidance() -> None:
    result = _invoke_verified({"raw_input": "", "store_context": "{}"})
    assert result["status"] == AgentStatus.SUCCESS.value
    assert "inventory" in result["output"].lower()
