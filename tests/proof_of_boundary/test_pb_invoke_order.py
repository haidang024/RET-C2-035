"""PB-6: verify BaseNode lifecycle ordering and S-1 denial."""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from datetime import date, timedelta
from typing import ClassVar

from framework.nodes.base_node import BaseNode
from framework.schemas.trust_level import TrustLevel


class _PrivilegedTrustGateFixture(BaseNode):
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _security_gate_input(self, state):
        return state

    def execute(self, state):
        return {"status": "success"}

    def _security_gate_output(self, result):
        return result


def _discover_node_classes() -> list[type]:
    pkg = importlib.import_module("src.nodes")
    discovered: list[type] = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseNode)
                and attr is not BaseNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


def _valid_state(node_cls: type) -> dict:
    processing_date = date.today()
    item = {
        "sku_id": "SKU-001",
        "name": "Apple",
        "quantity": 10,
        "expiry_date": (processing_date + timedelta(days=1)).isoformat(),
        "price": 120.0,
        "velocity": 3.0,
        "category": "produce",
    }
    store_context = json.dumps({"store_id": "S001", "report_format": "json"})
    report_output = json.dumps(
        {
            "report_date": processing_date.isoformat(),
            "store_id": "S001",
            "summary": {},
            "alerts": [],
            "markdown_recommendations": [],
        }
    )
    return {
        "caller_trust_level": node_cls.required_trust_level.value,
        "correlation_id": "pb6-invoke-order",
        "node_history": [],
        "error_log": [],
        "user_input": json.dumps({"raw_input": json.dumps([item]), "store_context": store_context}),
        "raw_input": json.dumps([item]),
        "validated_input": json.dumps([item]),
        "store_context": store_context,
        "inventory_items": json.dumps([item]),
        "validation_passed": True,
        "validation_errors": "[]",
        "sku_alerts": "[]",
        "markdown_recommendations": "[]",
        "report_output": report_output,
        "report_format": "json",
        "output_valid": True,
        "processing_date": processing_date.isoformat(),
        "error_code": None,
        "error_message": None,
        "status": "success",
        "result": report_output,
    }


class TestInvokeOrder:
    def test_s1_denial_refuses_execution_before_execute(self, monkeypatch):
        import framework.nodes.base_node as base_node_module

        events: list[str] = []
        execute_calls: list[object] = []
        monkeypatch.setattr(
            base_node_module,
            "emit_trace_event",
            lambda event_type, _payload, _state: events.append(event_type),
        )
        original_execute = _PrivilegedTrustGateFixture.execute

        def spy_execute(self, state):
            execute_calls.append(state)
            return original_execute(self, state)

        monkeypatch.setattr(_PrivilegedTrustGateFixture, "execute", spy_execute)
        result = _PrivilegedTrustGateFixture()(
            {
                "caller_trust_level": TrustLevel.ANONYMOUS.value,
                "correlation_id": "pb6-s1-denial",
            }
        )

        assert result["status"] == "error"
        assert "S-1" in result["error_log"][0]
        assert events == ["s1_denied"]
        assert not execute_calls

    def test_call_order_for_every_node(self, monkeypatch):
        import framework.nodes.base_node as base_node_module

        failures: list[str] = []
        for node_cls in _discover_node_classes():
            order: list[str] = []
            monkeypatch.setattr(
                base_node_module,
                "emit_trace_event",
                lambda event_type, _payload, _state, _order=order: _order.append(f"event:{event_type}"),
            )

            for method_name, label in (
                ("_security_gate_input", "security_gate_input"),
                ("execute", "execute"),
                ("_security_gate_output", "security_gate_output"),
            ):
                original = getattr(node_cls, method_name)

                def spy(self, arg, _order=order, _label=label, _original=original):
                    _order.append(_label)
                    return _original(self, arg)

                monkeypatch.setattr(node_cls, method_name, spy)

            node_cls()(_valid_state(node_cls))
            expected = [
                "event:node_start",
                "security_gate_input",
                "execute",
                "security_gate_output",
                "event:node_complete",
            ]
            if order != expected:
                failures.append(f"{node_cls.__name__}: expected {expected}, got {order}")

        assert not failures, "\n".join(failures)
