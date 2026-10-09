"""The surface other repositories depend on.

hamGwen pins this repository as a submodule and imports exactly the names below, and
nixos-helix packages a snapshot that exposes the `hamllm` console script. Adding
parameters with defaults is fine; removing or renaming anything listed here breaks a
consumer that only finds out when it bumps its pin. If one of these tests must change,
update the consumers in the same breath (see docs/CONSOLIDATION.md).
"""

import inspect
import unittest

from hamllm.agent import AgentRuntime, ToolRegistry
from hamllm.ollama import OllamaClient


def keyword_parameters(callable_):
    """Names that can be passed by keyword, and the ones that have no default."""
    params = [
        p
        for p in inspect.signature(callable_).parameters.values()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]
    return {p.name for p in params}, {p.name for p in params if p.default is p.empty}


class ConsumerContractTests(unittest.TestCase):
    def assert_accepts(self, callable_, names, *, required_subset_of=None):
        accepted, required = keyword_parameters(callable_)
        missing = set(names) - accepted
        self.assertFalse(missing, f"{callable_} no longer accepts {sorted(missing)}")
        # Consumers do not pass new parameters, so any new one must have a default.
        allowed = set(required_subset_of if required_subset_of is not None else names)
        extra_required = required - allowed - {"self"}
        self.assertFalse(
            extra_required, f"{callable_} now requires {sorted(extra_required)}"
        )

    def test_ollama_client_as_hamgwen_constructs_it(self):
        self.assert_accepts(OllamaClient.__init__, {"host", "timeout"})

    def test_ollama_client_chat_as_hamgwen_calls_it(self):
        self.assert_accepts(
            OllamaClient.chat,
            {"model", "messages", "tools", "think"},
            required_subset_of={"model", "messages"},
        )

    def test_agent_runtime_as_hamgwen_constructs_it(self):
        self.assert_accepts(
            AgentRuntime.__init__,
            {
                "client",
                "model",
                "tools",
                "reasoning",
                "response_policy",
                "max_tool_rounds",
                "max_response_rewrite_attempts",
                "safe_policy_fallback",
                "tool_observer",
            },
            required_subset_of={"client", "model"},
        )

    def test_agent_runtime_run_turn_takes_messages_and_an_approver(self):
        self.assert_accepts(
            AgentRuntime.run_turn,
            {"messages", "approver"},
            required_subset_of={"messages"},
        )

    def test_tool_registry_as_hamgwen_constructs_it(self):
        self.assert_accepts(
            ToolRegistry.__init__,
            {"schemas", "caller", "mutating_tools", "executing_tools"},
            required_subset_of=set(),
        )

    def test_console_script_target_exists_for_nixos_helix(self):
        from hamllm.cli import main

        self.assertTrue(callable(main))


if __name__ == "__main__":
    unittest.main()
