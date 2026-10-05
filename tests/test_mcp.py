import io
import json

import pytest

from hamllm import mcp
from hamllm.mcp import Server, serve
from hamllm.ollama import OllamaError

@pytest.fixture(autouse=True)
def default_model(monkeypatch):
    monkeypatch.setenv("HAMLLM_MODEL", "m")


PROFILE = {"m": {"categories": {"basic": 1.0, "instruction": 1.0}, "median_seconds": 1.0}}


class FakeClient:
    def __init__(self, response="hello", models=("m",), error=None):
        self.response, self._models, self.error, self.generated = response, list(models), error, []
        self.digests = {}

    def models(self):
        return self._models

    def installed(self):
        return {m: self.digests.get(m, "") for m in self._models}

    def generate(self, model, prompt, system=None, **kwargs):
        if self.error:
            raise self.error
        self.generated.append({"model": model, "prompt": prompt, "system": system, **kwargs})
        return self.response


def server(client=None, **kw):
    return Server(client or FakeClient(), num_ctx=8192, keep_alive="5m", load_profiles=lambda: PROFILE, **kw)


def rpc(srv, method, params=None, id=1):
    message = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        message["params"] = params
    return srv.handle(message)


def call(srv, name, **arguments):
    return rpc(srv, "tools/call", {"name": name, "arguments": arguments})["result"]


def test_initialize_negotiates_version_and_advertises_tools_only():
    result = rpc(server(), "initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert set(result["capabilities"]) == {"tools"}
    assert rpc(server(), "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == mcp.SUPPORTED_PROTOCOLS[0]


def test_notifications_get_no_response_and_unknown_methods_error():
    assert server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(server(), "resources/list")["error"]["code"] == -32601
    assert server().handle([{"jsonrpc": "2.0"}])["error"]["code"] == -32600  # batches unsupported


def test_tools_are_read_only_and_listed():
    names = [t["name"] for t in rpc(server(), "tools/list")["result"]["tools"]]
    assert names == ["ask_local", "local_models"]


def test_ask_local_sets_context_cap_and_keep_alive():
    client = FakeClient("a summary")
    result = call(server(client), "ask_local", prompt="summarise", system="be brief", max_tokens=99999)
    assert result["isError"] is False
    assert result["content"][0]["text"] == "a summary\n\n[local model: m]"
    sent = client.generated[0]
    assert sent["options"] == {"num_ctx": 8192, "num_predict": mcp.MAX_TOKENS_CEILING}
    assert sent["keep_alive"] == "5m" and sent["system"] == "be brief"


def test_ask_local_resolves_aliases_through_profiles():
    client = FakeClient(models=["m", "unprofiled"])
    assert call(server(client), "ask_local", prompt="x", model="fast")["isError"] is False
    assert client.generated[0]["model"] == "m"
    result = call(server(client), "ask_local", prompt="x", model="code")  # nothing passed coding
    assert result["isError"] and "no installed model" in result["content"][0]["text"]


def test_ask_local_reports_failures_as_tool_errors_not_protocol_errors():
    down = server(FakeClient(error=OllamaError("Cannot reach Ollama")))
    result = call(down, "ask_local", prompt="x")
    assert result["isError"] and "Cannot reach" in result["content"][0]["text"]
    empty = call(server(FakeClient("  ")), "ask_local", prompt="x")
    assert empty["isError"] and "no text" in empty["content"][0]["text"]
    for bad in ({}, {"prompt": ""}, {"prompt": "x", "max_tokens": 0}, {"prompt": "x", "max_tokens": True}, {"prompt": "x", "model": 3}):
        assert call(server(), "ask_local", **bad)["isError"] is True


def test_unknown_tool_is_a_protocol_error():
    assert rpc(server(), "tools/call", {"name": "rm_rf", "arguments": {}})["error"]["code"] == -32602


def test_local_models_reports_aliases_and_unavailable_reasons():
    data = json.loads(call(server(), "local_models")["content"][0]["text"])
    assert data["installed"] == ["m"] and data["profiles"].keys() == {"m"}
    assert data["aliases"]["fast"] == "m"
    assert "unavailable" in data["aliases"]["code"]


def test_serve_speaks_newline_delimited_jsonrpc_and_survives_garbage():
    lines = [
        "not json",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        "",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]
    out = io.StringIO()
    assert serve(server(), io.StringIO("\n".join(lines) + "\n"), out) == 0
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [None, 1, 2]
    assert replies[0]["error"]["code"] == -32700 and replies[1]["result"] == {}


def test_stale_profile_is_ignored_and_flagged_after_the_model_changes():
    saved = {"m": {**PROFILE["m"], "digest": "old"}}
    client = FakeClient()
    client.digests = {"m": "new"}
    srv = Server(client, num_ctx=8192, keep_alive="5m", load_profiles=lambda: saved)
    assert call(srv, "ask_local", prompt="x", model="fast")["isError"] is True
    data = json.loads(call(srv, "local_models")["content"][0]["text"])
    assert data["profiles"]["m"]["stale"] is True
    client.digests = {"m": "old"}
    assert call(srv, "ask_local", prompt="x", model="fast")["isError"] is False


def test_oversized_prompt_is_rejected_instead_of_silently_truncated():
    client = FakeClient()
    result = call(server(client), "ask_local", prompt="x" * (8192 * mcp.CHARS_PER_TOKEN + 4))
    assert result["isError"] and "window is 8192" in result["content"][0]["text"]
    assert client.generated == []
    assert call(server(client), "ask_local", prompt="x" * 1000)["isError"] is False


def test_unprofiled_models_are_not_loadable_over_mcp_except_the_default():
    client = FakeClient(models=["m", "big:70b"])
    result = call(server(client), "ask_local", prompt="x", model="big:70b")
    assert result["isError"] and "never been profiled" in result["content"][0]["text"]
    assert client.generated == []
    assert call(server(client), "ask_local", prompt="x", model="m")["isError"] is False  # default
    profiled = {**PROFILE, "big:70b": PROFILE["m"]}
    ok = Server(client, num_ctx=8192, keep_alive="5m", load_profiles=lambda: profiled)
    assert call(ok, "ask_local", prompt="x", model="big:70b")["isError"] is False
