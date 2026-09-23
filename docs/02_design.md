# Template Design Specification - RET-C2-035 Food Loss Alert Markdown Agent

## Position in AgentCore Architecture

- Agent Class: Graph
- Agent Name: FoodLossAlertMarkdownAgent
- L1 Base: AgentBaseGraph
- Category: Cat 2 - nested two-layer architecture
- Pattern: Retail food-loss alerting and markdown recommendation generation

### Three-Layer Separation

| Layer | Principle | Implementation |
|-------|-----------|---------------|
| State | Flat TypedDict composition | State(AgentState) in src/schemas/state.py using JSON-safe primitives and stringified payloads |
| Node | L1 inheritance (Template Method) | Outer and inner domain nodes use FunctionNode.execute with delta outputs |
| Graph | Composition (Builder) | Outer Graph(AgentBaseGraph) with GraphNode in main; inner DomainWorkflowGraph(BaseGraph) defines domain node topology |

---

## Cat 2 Two-Layer Architecture

```text
Outer backbone (AgentBaseGraph - fixed; add_edges not overridden):
  START -> initialize -> pre_process -> main -> post_process -> finalize -> END
                                       \-> RETRY (max 3) -> pre_process

  main slot = FoodLossWorkflowGraphNode(GraphNode)
    |
    +-> get_subgraph() -> DomainWorkflowGraph(BaseGraph) [inner graph]
         |
         +-> START
              -> input_parse        (InputParseNode)
              -> data_validate      (DataValidateNode)
              -> content_generate   (ContentGenerateNode)
              -> document_format    (DocumentFormatNode)
              -> output_validate    (OutputValidateNode)
              -> END
```

### File Layout

| File | Role |
|------|------|
| src/graph/graph.py | Outer graph - Graph(AgentBaseGraph) and FoodLossWorkflowGraphNode(GraphNode) |
| src/graph/domain_workflow_graph.py | Inner graph - DomainWorkflowGraph(BaseGraph) with complete BaseGraph method contract |
| src/nodes/pre_process_node.py | Outer pre_process - validates raw_input/store_context and normalizes report_format |
| src/nodes/post_process_node.py | Outer post_process - final status and result normalization |
| src/nodes/input_parse.py | Inner node 1 - parses raw JSON/CSV and runs PII detection gate |
| src/nodes/data_validate.py | Inner node 2 - validates inventory item schema and field constraints |
| src/nodes/content_generate.py | Inner node 3 - creates near-expiry alerts and markdown recommendations |
| src/nodes/document_format.py | Inner node 4 - builds final JSON or markdown report |
| src/nodes/output_validate.py | Inner node 5 - S-3 output safety and structural validation |
| src/schemas/state.py | Flat state schema for input, intermediate artifacts, output, and metadata |

---

## Node Configuration

### Outer Graph (AgentBaseGraph backbone)

| Slot | Node Class | Responsibility | Input State Fields | Output State Fields |
|------|------------|----------------|--------------------|---------------------|
| initialize | InitializeNode (default) | Framework bootstrap and metadata initialization | - | framework defaults |
| pre_process | PreProcessNode | Input envelope checks and report_format normalization | raw_input, user_input, store_context | validated_input, raw_input, store_context, report_format, status, error_code, error_message |
| main | FoodLossWorkflowGraphNode | Delegates to DomainWorkflowGraph and maps inner outputs back to outer state | validated_input/raw_input, store_context, report_format | inventory_items, validation_passed, validation_errors, sku_alerts, markdown_recommendations, report_output, output_valid, error_code, error_message, processing_date, status, result |
| post_process | PostProcessNode | Converts workflow outcome into final status/result contract | report_output, output_valid, error_code, error_message | status, result, error_code, error_message |
| finalize | FinalizeNode (default) | Framework finalize and response metadata composition | - | response_metadata |

### Inner Graph Domain Nodes (DomainWorkflowGraph)

| Node | Class | Responsibility | Input State Fields | Output State Fields |
|------|-------|----------------|--------------------|---------------------|
| input_parse | InputParseNode | Parse raw inventory input, detect PII patterns, set processing date | raw_input, store_context, error_code | inventory_items, processing_date, report_format or error_code/error_message |
| data_validate | DataValidateNode | Validate normalized records and collect validation errors | inventory_items, error_code | validation_passed, validation_errors and optional error_code/error_message |
| content_generate | ContentGenerateNode | Generate near-expiry alerts and markdown recommendations | inventory_items, validation_passed, processing_date, runtime config | sku_alerts, markdown_recommendations |
| document_format | DocumentFormatNode | Build daily report payload in JSON or markdown | sku_alerts, markdown_recommendations, store_context, inventory_items, processing_date, report_format | report_output |
| output_validate | OutputValidateNode | Enforce output safety and structure checks, set output_valid | report_output, report_format, error_code | output_valid and optional report_output blocker replacement |

---

## State Definition

```python
class State(AgentState):
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
```

State constraints (mandatory):
- Flat TypedDict only (primitives + JSON-serializable values)
- No JWT/API keys/credentials in state fields
- Invocation context and trust metadata are not stored in state payload
- No Pydantic/dataclass/custom object instances in state

---

## Security Implementation

| Layer | Implementation | Notes |
|-------|---------------|-------|
| S-1 | required_trust_level = TrustLevel.VERIFIED_EXTERNAL | Enforced at outer graph and outer nodes |
| S-2 | InputParseNode `_extra_security_gate_input` with PII patterns | Detects phone/card/email/secret patterns and returns PII_DETECTED |
| S-3 | OutputValidateNode `_extra_security_gate_output` and structural checks | Detects credentials in output and marks output invalid |
| S-4 | `emit_trace_event` in domain nodes | Node-level audit events emitted for domain execution states |
| S-5 | Framework-level credential safety discipline | Credentials never persisted to state and blocked in output validation |

---

## Framework Utilization

### Shared Components Used
- AgentBaseGraph (outer backbone)
- BaseGraph (inner domain workflow)
- GraphNode (FoodLossWorkflowGraphNode)
- FunctionNode (outer and inner domain nodes)
- AgentState (state base)
- AgentStatus (status signaling)
- TrustLevel (VERIFIED_EXTERNAL)
- emit_trace_event domain audit events

### Composition Pattern

- Pattern: GraphNode subgraph composition (Cat 2 nested)
- Composition target: FoodLossWorkflowGraphNode.get_subgraph() -> DomainWorkflowGraph
- Error propagation strategy: propagate (inner workflow errors bubble to outer status contract)

---

## Config Surface

### config/agent.yaml

```yaml
id: RET-C2-035
name: Food Loss Alert & Markdown Recommendation Agent
namespace: ret
version: 0.1.0
enabled: true
category: Cat 2
generation_mode: deterministic
industry: RET
base_type: AgentBaseGraph
class: src.graph.graph.Graph
required_trust_level: VERIFIED_EXTERNAL
requires:
  secrets: [AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT]
  extras: [openai]
```

### config/config.yaml

```yaml
max_retry: 3
timeout_s: 60
memory_enabled: false
stg_mock_mode: false

report_format: json
expiry_alert_days: 3

markdown_tiers:
  TIER_1:
    days_threshold: 1
    markdown_pct: 50.0
  TIER_2:
    days_threshold: 2
    markdown_pct: 30.0
  TIER_3:
    days_threshold: 3
    markdown_pct: 15.0

hitl:
  enabled: false
  max_hitl: 5
```

### Runtime Configuration and LLM Flow

`config/agent.yaml` contains only static registry metadata, while
`config/config.yaml` contains food-loss and runtime controls. The standalone server
provisions chained invocation secrets, while `src/services/llm_runtime.py`
constructs Azure OpenAI clients per invocation. Provider failure does not change
the deterministic workflow result, and no credential enters State.

---

## Import Isolation Confirmation

- No Level 0 SDK import in runtime source
- Imports are framework.*, src.*, and Python standard library
- No agents/base import path usage

---

## EU AI Act Art.13 Design-Time Evidence (Advisory until 2026-09-01; required from 2026-09-01 when `docs/01_proposal.md` declares Annex III `In scope`)

The proposal declares this use case not in scope; these transparency controls are
retained as good practice.

| Evidence item | Design reference / description |
|---------------|--------------------------------|
| Intended purpose and operating context | Daily food-loss alerts, price-markdown recommendations, and structured operational reporting for perishable retail inventory. |
| System capabilities and limitations | Bounded JSON/CSV parsing, validation, deterministic threshold rules, and report formatting; no autonomous pricing action or inventory mutation. |
| User-facing transparency information | Output includes alert severity, expiry timing, current and recommended price, markdown percentage/tier, validation status, and report metadata. |
| Human oversight mechanism | Retail operators review recommendations before changing prices; input and output safety gates reject invalid or sensitive content. |

---

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Workflow is fixed-stage pipeline and does not require autonomous planning loop |
| Composition pattern | Flat single graph only | GraphNode + inner BaseGraph | Cat 2 nested | Domain workflow has multiple processing stages with explicit contracts |
| Input format handling | JSON only | JSON and CSV | JSON and CSV | Existing upstream systems provide both formats |
| Output format handling | JSON only | JSON and markdown | JSON and markdown | Supports both downstream automation and operator readability |
| Trust level | INTERNAL | VERIFIED_EXTERNAL | VERIFIED_EXTERNAL | Caller is authenticated external retail operation context |
