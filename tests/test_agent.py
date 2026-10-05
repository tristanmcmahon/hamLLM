import json

from hamllm.agent import AgentRuntime, ToolRegistry


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, model, messages, *, tools=None, think=None):
        self.calls.append({"model": model, "messages": list(messages), "tools": tools, "think": think})
        return self.responses.pop(0)


def tool_call(name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        }
    }


def answer(content):
    return {"message": {"role": "assistant", "content": content}}


def test_duplicate_observation_is_not_executed_twice():
    client = FakeClient([tool_call("inspect", {"path": "a"}), tool_call("inspect", {"path": "a"}), answer("done")])
    calls = []

    def caller(name, arguments, *, allow_mutation=False):
        calls.append((name, arguments, allow_mutation))
        return json.dumps({"ok": True, "result": "x"})

    runtime = AgentRuntime(client=client, model="gwen", tools=ToolRegistry(schemas=[{"x": 1}], caller=caller))
    messages = [{"role": "user", "content": "inspect"}]

    assert runtime.run_turn(messages) == "done"
    assert calls == [("inspect", {"path": "a"}, False)]
    assert "duplicate tool call" in messages[-2]["content"]


def test_mutation_defaults_to_denied():
    client = FakeClient([tool_call("write", {"path": "a"}), answer("denied")])
    calls = []

    def caller(name, arguments, *, allow_mutation=False):
        calls.append(name)
        return json.dumps({"ok": True})

    runtime = AgentRuntime(
        client=client,
        model="gwen",
        tools=ToolRegistry(caller=caller, mutating_tools=frozenset({"write"})),
    )
    messages = [{"role": "user", "content": "write"}]

    assert runtime.run_turn(messages) == "denied"
    assert calls == []
    assert "not approved" in messages[-2]["content"]


def test_successful_mutation_invalidates_observation_cache():
    client = FakeClient([
        tool_call("inspect", {"path": "a"}),
        tool_call("write", {"path": "a"}),
        tool_call("inspect", {"path": "a"}),
        answer("done"),
    ])
    calls = []

    def caller(name, arguments, *, allow_mutation=False):
        calls.append((name, allow_mutation))
        return json.dumps({"ok": True})

    runtime = AgentRuntime(
        client=client,
        model="gwen",
        tools=ToolRegistry(caller=caller, mutating_tools=frozenset({"write"})),
    )
    messages = [{"role": "user", "content": "change it"}]

    assert runtime.run_turn(messages, approver=lambda name, arguments: True) == "done"
    assert calls == [("inspect", False), ("write", True), ("inspect", False)]


def test_tool_budget_finishes_without_tools_and_reports_constraint():
    client = FakeClient([tool_call("inspect", {}), answer("I only verified the first step")])

    runtime = AgentRuntime(
        client=client,
        model="gwen",
        tools=ToolRegistry(caller=lambda *args, **kwargs: json.dumps({"ok": True})),
        max_tool_rounds=1,
    )
    messages = [{"role": "user", "content": "do several things"}]

    assert runtime.run_turn(messages) == "I only verified the first step"
    assert client.calls[-1]["tools"] is None
    assert "tool budget" in client.calls[-1]["messages"][-1]["content"].lower()


def test_blocked_final_answer_is_rewritten_without_tools():
    client = FakeClient([answer("blocked text"), answer("safe text")])

    def policy(text):
        return ("test-rule",) if "blocked" in text else ()

    runtime = AgentRuntime(client=client, model="gwen", response_policy=policy)
    messages = [{"role": "user", "content": "answer"}]

    assert runtime.run_turn(messages) == "safe text"
    assert client.calls[-1]["tools"] is None
    assert messages[-1]["content"] == "safe text"


def test_options_reach_the_client_only_when_configured():
    class Recording:
        def __init__(self):
            self.kwargs = []

        def chat(self, model, messages, **kwargs):
            self.kwargs.append(kwargs)
            return answer("ok")

    plain, tuned = Recording(), Recording()
    AgentRuntime(client=plain, model="m").run_turn([{"role": "user", "content": "x"}])
    AgentRuntime(client=tuned, model="m", options={"num_ctx": 8192}).run_turn([{"role": "user", "content": "x"}])
    assert "options" not in plain.kwargs[0]
    assert tuned.kwargs[0]["options"] == {"num_ctx": 8192}
