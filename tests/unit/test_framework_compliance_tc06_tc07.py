"""TC-06/TC-07: framework final security gates cannot be overridden."""

import pytest

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel


class TestFunctionNodeFinalSecurityGates:
    def test_tc06_security_gate_input_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError, match="Cannot override '_security_gate_input'"):

            class InvalidInputGateNode(FunctionNode):
                required_trust_level = TrustLevel.VERIFIED_EXTERNAL

                def _security_gate_input(self, state):
                    return state

                def execute(self, state):
                    return {"status": AgentStatus.SUCCESS.value}

    def test_tc07_security_gate_output_cannot_be_overridden(self) -> None:
        with pytest.raises(TypeError, match="Cannot override '_security_gate_output'"):

            class InvalidOutputGateNode(FunctionNode):
                required_trust_level = TrustLevel.VERIFIED_EXTERNAL

                def _security_gate_output(self, result):
                    return result

                def execute(self, state):
                    return {"status": AgentStatus.SUCCESS.value}
