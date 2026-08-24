from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .ollama import OllamaClient

ToolApprover = Callable[[str, dict[str, Any]], bool]
ToolObserver = Callable[[str, dict[str, Any]], None]
ResponsePolicy = Callable[[str], tuple[str, ...]]

SAFE_POLICY_FALLBACK = (
    "I’m not returning that draft because it violated a deterministic response policy. "
    "I can still help with a safer alternative."
)


def allow_all_responses(_: str) -> tuple[str, ...]:
    return ()


@dataclass(frozen=True)
class ToolRegistry:
    schemas: list[dict[str, Any]] = field(default_factory=list)
    caller: Callable[..., str] | None = None
    mutating_tools: frozenset[str] = frozenset()
    executing_tools: frozenset[str] = frozenset()

    @property
    def approval_required_tools(self) -> frozenset[str]:
        return self.mutating_tools | self.executing_tools

    def call_tool(self, name: str, arguments: dict[str, Any], *, allow_mutation: bool = False) -> str:
        if self.caller is None:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
        return self.caller(name, arguments, allow_mutation=allow_mutation)


@dataclass
class AgentRuntime:
    client: OllamaClient
    model: str
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    reasoning: str | None = None
    response_policy: ResponsePolicy = allow_all_responses
    max_tool_rounds: int = 24
    max_response_rewrite_attempts: int = 1
    safe_policy_fallback: str = SAFE_POLICY_FALLBACK
    tool_observer: ToolObserver | None = None

    def _chat(self, messages: list[dict[str, Any]], *, allow_tools: bool = True) -> dict[str, Any]:
        schemas = self.tools.schemas if allow_tools and self.tools.schemas else None
        return self.client.chat(
            self.model,
            messages,
            tools=schemas,
            think=self.reasoning,
        )

    @staticmethod
    def _assistant_message(response: dict[str, Any]) -> dict[str, Any]:
        message = response.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama response did not contain a message")
        result: dict[str, Any] = {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "thinking", "tool_calls"}
        }
        result.setdefault("role", "assistant")
        result.setdefault("content", "")
        return result

    @staticmethod
    def _tool_signature(name: str, arguments: dict[str, Any]) -> str:
        return json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _tool_result_succeeded(result: str) -> bool:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict) and payload.get("ok") is True

    def _finalize_answer(self, messages: list[dict[str, Any]]) -> str:
        assistant_message = messages[-1]
        content = str(assistant_message.get("content", "")).strip()
        blocked_rules = self.response_policy(content)
        if not blocked_rules:
            return content

        for _ in range(self.max_response_rewrite_attempts):
            rewrite_context = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "The previous draft violated deterministic response policy rules: "
                        + ", ".join(blocked_rules)
                        + ". Rewrite the answer now without reproducing or providing the blocked content. "
                        "Preserve useful diagnosis and safer alternatives. No tools are available for this rewrite."
                    ),
                },
            ]
            revised = self._assistant_message(self._chat(rewrite_context, allow_tools=False))
            revised_content = str(revised.get("content", "")).strip()
            blocked_rules = self.response_policy(revised_content)
            if not blocked_rules:
                messages[-1] = revised
                return revised_content

        messages[-1] = {"role": "assistant", "content": self.safe_policy_fallback}
        return self.safe_policy_fallback

    def run_turn(
        self,
        messages: list[dict[str, Any]],
        *,
        approver: ToolApprover | None = None,
    ) -> str:
        seen_observations: set[str] = set()
        seen_mutations: set[str] = set()
        seen_executions: set[str] = set()
        approve = approver or (lambda _name, _arguments: False)

        for _ in range(self.max_tool_rounds):
            assistant_message = self._assistant_message(self._chat(messages))
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                return self._finalize_answer(messages)

            for tool_call in tool_calls:
                function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                name = function.get("name")
                arguments = function.get("arguments", {})
                if not isinstance(name, str):
                    result = json.dumps({"ok": False, "error": "malformed tool call: missing function name"})
                    name = "unknown"
                elif not isinstance(arguments, dict):
                    result = json.dumps({"ok": False, "error": "malformed tool call: arguments must be an object"})
                else:
                    if self.tool_observer is not None:
                        self.tool_observer(name, arguments)
                    signature = self._tool_signature(name, arguments)
                    if name in self.tools.mutating_tools:
                        if signature in seen_mutations:
                            result = json.dumps({"ok": False, "error": "duplicate mutating tool call in this turn; it will not be executed twice"})
                        else:
                            seen_mutations.add(signature)
                            if approve(name, arguments):
                                result = self.tools.call_tool(name, arguments, allow_mutation=True)
                                if self._tool_result_succeeded(result):
                                    seen_observations.clear()
                                    seen_executions.clear()
                            else:
                                result = json.dumps({"ok": False, "error": "action was not approved by the user"})
                    elif name in self.tools.executing_tools:
                        if signature in seen_executions:
                            result = json.dumps({"ok": False, "error": "duplicate executing tool call in the current workspace state; it will not be run twice"})
                        else:
                            seen_executions.add(signature)
                            if approve(name, arguments):
                                result = self.tools.call_tool(name, arguments, allow_mutation=True)
                                if self._tool_result_succeeded(result):
                                    seen_observations.clear()
                            else:
                                result = json.dumps({"ok": False, "error": "action was not approved by the user"})
                    elif name in self.tools.approval_required_tools:
                        result = json.dumps({"ok": False, "error": "approval-required tool was not classified by the runtime"})
                    elif signature in seen_observations:
                        result = json.dumps({"ok": False, "error": "duplicate tool call in the current workspace state; the previous result is already in context"})
                    else:
                        seen_observations.add(signature)
                        result = self.tools.call_tool(name, arguments)

                messages.append({"role": "tool", "tool_name": name, "content": result})

        final_context = [
            *messages,
            {
                "role": "system",
                "content": (
                    "The tool budget for this turn is exhausted. No more tools are available. "
                    "Do not claim that any requested edit, execution, staging, commit, or other action completed "
                    "unless a successful tool result already in this conversation proves it. "
                    "Answer using only the evidence already gathered and state plainly which requested actions "
                    "remain incomplete or uncertain."
                ),
            },
        ]
        assistant_message = self._assistant_message(self._chat(final_context, allow_tools=False))
        messages.append(assistant_message)
        return self._finalize_answer(messages)
