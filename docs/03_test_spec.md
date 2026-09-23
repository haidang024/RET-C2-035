# Test Specification - RET-C2-035

## Test Strategy

- Coverage target: 80%+ on src/nodes and src/graph
- Test types: Unit and Proof-of-Boundary
- Scope: Cat 2 graph behavior, security gate behavior, parsing/validation/business-output contracts

---

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | State schema uses JSON-safe fields only | PASS |
| TC-02 | Error signaling on invalid input | Invalid pre_process/input_parse paths set error_code and error_message | PASS |
| TC-03 | No credential leakage in output | Credential-like output is blocked by output gate | PASS |
| TC-04 | Invocation context isolation | Context is constructed only at framework/adapter boundaries and is never persisted as a State object | PASS |
| TC-05 | S-4 duplicate lifecycle event guard | Domain traces are emitted without duplicating framework lifecycle events | PASS |
| TC-06 | S-2 final gate | Overriding `_security_gate_input()` raises `TypeError`; domain logic uses `_extra_security_gate_input()` | PASS |
| TC-07 | S-3 final gate | Overriding `_security_gate_output()` raises `TypeError`; domain logic uses `_extra_security_gate_output()` | PASS |
| TC-08 | required_trust_level declared | Outer graph and outer nodes require VERIFIED_EXTERNAL | PASS |
| TC-09 | Non-trivial input checks | Parse/validation rules cover required fields, date format, numeric ranges | PASS |
| TC-10 | Non-trivial output checks | OutputValidateNode checks content safety and JSON required keys | PASS |
| TC-11 | Domain emit_trace_event presence | Domain nodes emit _emit_trace_event at major execution points | PASS |

---

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode -> EventEmitter | Domain nodes execute with trace emission on invocation paths | No silent failure | PASS |
| PB-2 | State serialization | Graph result remains JSON-serializable | Serialization succeeds | PASS |
| PB-3 | Cat 2 invoke boundary | Graph.invoke executes outer+inner workflow end-to-end | Happy-path returns valid output | PASS |
| PB-4 | Import isolation | No Level 0 SDK imports in runtime source | Zero violations | PASS |
| PB-5 | Checkpoint safety *(conditional)* | Inspect all persisted surfaces only when checkpointing is enabled | Auto-waived — checkpointing disabled |
| PB-6 | Invoke lifecycle | S-1 → node_start → S-2 → execute → S-3 → node_complete for every concrete node; denial occurs before execute | PASS |
| PB-7 | HITL propagation *(conditional)* | Required only when `hitl.enabled: true` | Auto-waived — non-HITL |
| PB-8 | Standalone config, LLM, and auth | Runtime config loads; key-less boot works; one optional LLM reaches the inner graph; external bearer never elevates to INTERNAL | PASS |

Reference tests:
- tests/unit/test_workflow_nodes.py
- tests/unit/test_framework_compliance_tc06_tc07.py
- tests/proof_of_boundary/test_security_pipeline.py
- tests/proof_of_boundary/test_pb_invoke_order.py
- tests/proof_of_boundary/test_server_llm_injection.py

---

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | JSON parse success | raw_input JSON list with valid SKU fields | inventory_items JSON generated and error_code None | PASS |
| BL-02 | Validation failure on date format | expiry_date not YYYY-MM-DD | validation_passed false and VALIDATION_ERROR | PASS |
| BL-03 | Alert/recommendation generation | near-expiry item within alert horizon | sku_alerts and markdown_recommendations each contain matching record | PASS |
| BL-04 | JSON document format generation | valid intermediate state and report_format=json | report_output contains summary and required report sections | PASS |
| BL-05 | Output JSON schema validation | report_output missing required keys | output_valid false | PASS |
| BL-06 | End-to-end graph happy path | valid raw_input and store_context | status SUCCESS, output_valid true, non-empty report_output | PASS |
| BL-07 | Empty input error path | raw_input empty | status ERROR and result empty string | PASS |

---

## Test Execution Summary

- Execution date: 2026-08-18
- Full suite: 25 collected; 22 passed and 3 conditionally skipped.
- Proof-of-boundary suite: 18 collected; 15 passed and 3 conditionally skipped.
- Stage 5 provisional health and authenticated invoke evidence: PASS.
- Expected skips: PB-5 because checkpointing is disabled and two PB-7 cases because HITL is disabled.
