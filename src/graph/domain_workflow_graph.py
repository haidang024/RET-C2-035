"""RET-C2-035 inner domain workflow graph."""

from __future__ import annotations

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.content_generate import ContentGenerateNode
from src.nodes.data_validate import DataValidateNode
from src.nodes.document_format import DocumentFormatNode
from src.nodes.input_parse import InputParseNode
from src.nodes.output_validate import OutputValidateNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow for food-loss alert processing."""

    @property
    def name(self) -> str:
        return "FoodLossAlertMarkdownAgent_domain_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        if self.config.get("expiry_alert_days") is None:
            raise ValueError("DomainWorkflowGraph: missing required config key: expiry_alert_days")
        if not isinstance(self.config.get("markdown_tiers"), dict):
            raise ValueError("DomainWorkflowGraph: markdown_tiers must be a mapping")

    def register_nodes(self) -> None:
        self._nodes["input_parse"] = InputParseNode()
        self._nodes["data_validate"] = DataValidateNode()
        self._nodes["content_generate"] = ContentGenerateNode(config=self.config)
        self._nodes["document_format"] = DocumentFormatNode()
        self._nodes["output_validate"] = OutputValidateNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "input_parse")
        self._sg.add_edge("input_parse", "data_validate")
        self._sg.add_conditional_edges("data_validate", self.route)
        self._sg.add_edge("content_generate", "document_format")
        self._sg.add_edge("document_format", "output_validate")
        self._sg.add_edge("output_validate", END)

    def route(self, state: AgentState) -> str:
        if state.get("error_code"):
            return "output_validate"  # jump straight to S-3 gate
        return "content_generate"

    def get_output(self, state: AgentState) -> dict:
        error_code = state.get("error_code")
        output_valid = bool(state.get("output_valid"))
        status = AgentStatus.ERROR.value if (error_code or not output_valid) else AgentStatus.SUCCESS.value
        return {
            "inventory_items": state.get("inventory_items", "[]"),
            "validation_passed": state.get("validation_passed", False),
            "validation_errors": state.get("validation_errors", "[]"),
            "sku_alerts": state.get("sku_alerts", "[]"),
            "markdown_recommendations": state.get("markdown_recommendations", "[]"),
            "report_output": state.get("report_output", ""),
            "report_format": state.get("report_format", "json"),
            "output_valid": output_valid,
            "error_code": error_code,
            "error_message": state.get("error_message"),
            "processing_date": state.get("processing_date", ""),
            "status": status,
            "trace_id": state.get("trace_id"),
            "node_history": state.get("node_history", []),
        }
