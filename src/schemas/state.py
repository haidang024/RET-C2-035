"""RET-C2-035 flat state schema."""

from __future__ import annotations

from typing import Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Flat, JSON-serializable state for RET-C2-035."""

    # Input
    raw_input: Optional[str]
    store_context: Optional[str]

    # Outer pre_process
    validated_input: Optional[str]

    # Parsed / validated
    inventory_items: Optional[str]
    validation_passed: Optional[bool]
    validation_errors: Optional[str]

    # Generated content
    sku_alerts: Optional[str]
    markdown_recommendations: Optional[str]

    # Formatted output
    report_output: Optional[str]
    report_format: Optional[str]
    output_valid: Optional[bool]

    # Metadata / errors
    error_code: Optional[str]
    error_message: Optional[str]
    processing_date: Optional[str]
    trace_id: Optional[str]

    # Final output compatibility
    status: Optional[str]
    result: Optional[str]
    input_error_message: str | None
    input_error_guidance: list[str]
    generation_mode: str | None
    provider_error_message: str | None
