from hamllm import cli


def test_bare_command_preserves_bridge(monkeypatch):
    monkeypatch.setattr(cli.bridge, "main", lambda argv=None: 7)
    assert cli.main([]) == 7


def test_explicit_bridge(monkeypatch):
    monkeypatch.setattr(cli.bridge, "main", lambda argv=None: 3)
    assert cli.main(["bridge"]) == 3


def test_one_shot_chat(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, host, timeout):
            assert host

        def chat(self, model, messages, think=None):
            assert model == "test-model"
            assert messages[-1]["content"] == "hello world"
            return {"message": {"role": "assistant", "content": "ham!"}}

    monkeypatch.setattr(cli, "OllamaClient", FakeClient)

    assert cli.main(["chat", "--model", "test-model", "hello", "world"]) == 0
    assert capsys.readouterr().out.strip() == "ham!"
