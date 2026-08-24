import json

from hamllm import ollama


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_generate_uses_normalized_host(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"response": "hello"})

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)
    client = ollama.OllamaClient(host="127.0.0.1:11434", timeout=12)

    assert client.generate("gwen", "hi") == "hello"
    assert seen["url"] == "http://127.0.0.1:11434/api/generate"
    assert seen["timeout"] == 12
    assert seen["payload"]["model"] == "gwen"


def test_chat_returns_full_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"message": {"role": "assistant", "content": "answer"}})

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)
    response = ollama.OllamaClient().chat("gwen", [{"role": "user", "content": "q"}])

    assert response["message"]["content"] == "answer"


def test_legacy_call_ollama_keeps_full_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return FakeResponse({"response": "legacy"})

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)

    assert ollama.call_ollama("http://localhost:11434/api/generate", "m", "p") == "legacy"
    assert seen["url"] == "http://localhost:11434/api/generate"
