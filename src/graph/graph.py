"""RET-C2-035 outer graph (Cat 2 nested architecture)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.utils.config_loader import load_config

from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class FoodLossWorkflowGraphNode(GraphNode):
    """GraphNode wrapper for RET-C2-035 inner workflow."""

    # "handle", not "propagate": a propagated SubgraphError is raised before
    # merge_output() runs, so the inner graph's error_code/error_message are
    # discarded and PostProcessNode sees error_code=None — it cannot tell the
    # caller what went wrong (Harness G2). on_subgraph_error() keeps those
    # fields on the state instead.
    error_strategy: ClassVar[str] = "handle"
    propagate_hitl: ClassVar[bool] = False

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config or {}
        self._llm = llm

    def get_subgraph(self) -> Any:
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        return DomainWorkflowGraph(config=self._parent_config())

    def extract_input(self, state: AgentState) -> str:
        return json.dumps(
            {
                "raw_input": state.get("validated_input", state.get("raw_input", state.get("user_input", ""))),
                "store_context": state.get("store_context", "{}"),
                "error_code": state.get("error_code"),
                "error_message": state.get("error_message"),
                "processing_date": state.get("processing_date", ""),
                "report_format": state.get("report_format", "json"),
            }
        )

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("input_error_message"):
            return {"status": AgentStatus.SUCCESS.value}

        # Harness G2: GraphNode.execute() raises/handles SubgraphError *before*
        # calling merge_output(), so on the inner-error path the inner graph's
        # own error_code/error_message never reach the parent state and
        # PostProcessNode sees error_code=None. Invoke the subgraph here so the
        # error path goes through merge_output() exactly like the success path.
        ctx = replace(
            InvocationContext.from_state(state),
            hitl_allowed=self.propagate_hitl and state.get("hitl_allowed", True),
        )
        subgraph = self.get_subgraph()
        try:
            sub_result = subgraph.invoke(self.extract_input(state), session_id=ctx.session_id, ctx=ctx)
        except Exception as exc:
            return cast(dict[str, Any], self._handle_call_error(subgraph, exc, state))
        return self.merge_output(state, sub_result)

    def on_subgraph_error(self, state: AgentState, error: Exception) -> dict[str, Any]:
        """Preserve the inner failure as state fields so post_process can report it.

        Keeps status=ERROR: route() sends it through PostProcessNode, which
        decides whether the failure is caller-fixable (reported as success with
        the reason) or infrastructure (stays ERROR so monitoring alerts).
        """
        del state
        error_log = getattr(error, "error_log", None) or []
        # error_log entries are framework-formatted "<Node>: <msg>\n<traceback>".
        # Keep only the first line and drop the node-name prefix so nothing
        # internal reaches the caller (Harness H3).
        detail = ""
        for raw in reversed([str(e) for e in error_log if str(e).strip()]):
            first_line = raw.splitlines()[0].strip()
            _, sep, tail = first_line.partition(": ")
            detail = (tail if sep else first_line).strip()
            if detail:
                break
        # status stays SUCCESS here for the same G1 reason as merge_output():
        # PostProcessNode must actually run to classify and report the failure.
        return {
            "status": AgentStatus.SUCCESS.value,
            "error_code": "WORKFLOW_ERROR",
            "error_message": detail or "The food-loss workflow could not be completed.",
        }

    def merge_output(self, state: AgentState, sub_result: dict) -> dict:
        del state
        return {
            "inventory_items": sub_result.get("inventory_items", "[]"),
            "validation_passed": sub_result.get("validation_passed", False),
            "validation_errors": sub_result.get("validation_errors", "[]"),
            "sku_alerts": sub_result.get("sku_alerts", "[]"),
            "markdown_recommendations": sub_result.get("markdown_recommendations", "[]"),
            "report_output": sub_result.get("report_output", ""),
            "report_format": sub_result.get("report_format", "json"),
            "output_valid": sub_result.get("output_valid", False),
            "error_code": sub_result.get("error_code"),
            "error_message": sub_result.get("error_message"),
            "processing_date": sub_result.get("processing_date", ""),
            # Harness G1: BaseNode.__call__() short-circuits any node whose
            # incoming state already has status=="error" — execute() is skipped
            # entirely. Handing status=error to the next node therefore means
            # PostProcessNode never runs and the caller gets nothing at all.
            # The failure travels as error_code/error_message (declared in the
            # State schema, so LangGraph keeps them) and PostProcessNode decides
            # the final status.
            "status": AgentStatus.SUCCESS.value,
            "result": sub_result.get("report_output", ""),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {**self._config, "llm": self._llm}


class Graph(AgentBaseGraph):
    """FoodLossAlertMarkdownAgent outer graph."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    # Harness J2/J4: the Marketplace runner constructs the agent with a bare
    # ``agent_cls()`` on agentcore 1.0.1 and ``agent_cls(config=...)`` on 1.0.3,
    # and it never reads ``config/config.yaml``. The inner DomainWorkflowGraph
    # requires ``expiry_alert_days`` and raises at compile time without it, so
    # on the container path every request failed before any node ran. Loading
    # the file here makes both runner generations work; ``**kwargs`` absorbs
    # arguments added by later runner versions.
    def __init__(self, config: dict[str, Any] | None = None, **kwargs: Any) -> None:
        # Load config/config.yaml first, then overlay whatever the runner passed.
        # agentcore 1.0.1 calls agent_cls() (config=None) but 1.0.3 calls
        # agent_cls(config={...}) — often an EMPTY dict. Keying off `is None`
        # alone therefore skipped the file load on 1.0.3 and left required keys
        # missing, which surfaced as a bare
        # "Graph invocation did not succeed: status='error'".
        config_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
        file_config = load_config(str(config_path)) if config_path.exists() else {}
        config = {**file_config, **dict(config or {})}
        super().__init__(config=dict(config), **kwargs)

    def route(self, state: AgentState) -> str:
        """Send ERROR through post_process instead of straight to finalize.

        Harness G5: the SDK default routes ERROR directly to finalize, so the
        node that turns a failure into a caller-readable report never runs and
        the caller receives nothing. PostProcessNode decides which failures are
        caller-fixable (reported as success with the reason) and which stay
        ERROR for monitoring.
        """
        if state.get("status", "") == AgentStatus.ERROR.value:
            return "post_process"
        return cast(str, super().route(state))

    @property
    def name(self) -> str:
        return "FoodLossAlertMarkdownAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = FoodLossWorkflowGraphNode(
            config=self.config,
            llm=self.config.get("llm"),
        )
        self._nodes["post_process"] = PostProcessNode(
            llm=self.config.get("llm"),
            config=self.config,
        )

    def get_output(self, state: AgentState) -> dict[str, Any]:
        output = {
            "output": state.get("result", ""),
            "result": state.get("result", ""),
            "report_output": state.get("report_output", ""),
            "output_valid": state.get("output_valid", False),
            "status": state.get("status", AgentStatus.ERROR.value),
            "error_code": state.get("error_code"),
            "error_message": state.get("error_message"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
        output["generation_mode"] = state.get("generation_mode")
        output["provider_error_message"] = state.get("provider_error_message")
        context = state.get("input_context")
        is_marketplace = isinstance(context, dict) and "conversation_history" in context
        if not is_marketplace:
            return output
        if _set_marketplace_guidance(output, state, "Food-loss alert request"):
            return output
        report = self._parse_report(output.get("output"))
        if report is not None:
            output["output"] = self._render_marketplace_report(report)
        return output

    @staticmethod
    def _parse_report(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _render_marketplace_report(report: dict[str, Any]) -> str:
        summary = report.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        lines = [
            "# Daily Food-Loss Risk Report",
            "",
            f"**Date:** {report.get('report_date', 'unknown')}",
            f"**Store:** {report.get('store_name', report.get('store_id', 'unknown'))}",
            "",
            "## Summary",
            "",
            f"- SKUs scanned: {summary.get('total_skus_scanned', 0)}",
            f"- Alerts: {summary.get('alert_count', 0)}",
            f"- High-severity alerts: {summary.get('high_severity_count', 0)}",
            f"- Estimated loss risk: JPY {summary.get('estimated_loss_risk_jpy', 0)}",
        ]
        alerts = report.get("alerts")
        if isinstance(alerts, list) and alerts:
            lines.extend(["", "## Near-expiry alerts", ""])
            for item in alerts[:30]:
                if isinstance(item, dict):
                    lines.append(
                        f"- {item.get('sku_id', 'unknown')}: {item.get('name', 'Item')} — "
                        f"{item.get('days_until_expiry', '?')} day(s), severity {item.get('severity', 'unknown')}"
                    )
        recommendations = report.get("markdown_recommendations")
        if isinstance(recommendations, list) and recommendations:
            lines.extend(["", "## Markdown recommendations", ""])
            for item in recommendations[:30]:
                if isinstance(item, dict):
                    lines.append(
                        f"- {item.get('sku_id', 'unknown')}: {item.get('markdown_pct', 0)}% "
                        f"({item.get('tier', 'standard')})"
                    )
        if report.get("regulatory_note"):
            lines.extend(["", f"> {report['regulatory_note']}"])
        return "\n".join(lines)


def _set_marketplace_guidance(output: dict[str, Any], state: AgentState, subject: str) -> bool:
    context = state.get("input_context")
    message = state.get("input_error_message")
    if not (isinstance(context, dict) and "conversation_history" in context and message):
        return False
    lines = [f"{subject} could not be processed.", "", f"Reason: {message}"]
    guidance = state.get("input_error_guidance")
    if isinstance(guidance, list) and guidance:
        lines.extend(["", "How to continue:"])
        lines.extend(f"- {item}" for item in guidance)
    output["output"] = "\n".join(lines)
    return True
