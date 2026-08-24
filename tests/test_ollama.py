import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from hamllm.ollama import OllamaClient, OllamaError


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OllamaClientTests(unittest.TestCase):
    def test_host_must_be_an_http_url(self):
        with self.assertRaisesRegex(ValueError, "http"):
            OllamaClient("localhost:11434")

    @patch("urllib.request.urlopen")
    def test_models_are_sorted(self, urlopen):
        urlopen.return_value = Response(
            {"models": [{"name": "qwen3.6:27b"}, {"name": "gpt-oss:20b"}]}
        )
        self.assertEqual(
            OllamaClient("http://localhost:11434").models(),
            ["gpt-oss:20b", "qwen3.6:27b"],
        )

    @patch("urllib.request.urlopen")
    def test_generate_sends_non_streaming_payload(self, urlopen):
        urlopen.return_value = Response({"response": "local answer"})
        client = OllamaClient("http://localhost:11434")
        self.assertEqual(client.generate("gpt-oss:20b", "hello"), "local answer")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:11434/api/generate")
        self.assertEqual(
            json.loads(request.data),
            {"model": "gpt-oss:20b", "prompt": "hello", "stream": False},
        )

    @patch("urllib.request.urlopen")
    def test_chat_preserves_full_response_for_agent_runtime(self, urlopen):
        payload = {"message": {"role": "assistant", "content": "hello"}}
        urlopen.return_value = Response(payload)
        response = OllamaClient("http://localhost:11434").chat(
            "gpt-oss:20b", [{"role": "user", "content": "hi"}]
        )
        self.assertEqual(response, payload)

    @patch("urllib.request.urlopen")
    def test_chat_content_extracts_assistant_content(self, urlopen):
        urlopen.return_value = Response(
            {"message": {"role": "assistant", "content": "hello"}}
        )
        response = OllamaClient("http://localhost:11434").chat_content(
            "gpt-oss:20b", [{"role": "user", "content": "hi"}]
        )
        self.assertEqual(response, "hello")

    @patch("urllib.request.urlopen")
    def test_http_errors_become_clear_ollama_errors(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "http://localhost/api/tags", 500, "error", {}, io.BytesIO(b"broken")
        )
        with self.assertRaisesRegex(OllamaError, "HTTP 500: broken"):
            OllamaClient("http://localhost:11434").models()


if __name__ == "__main__":
    unittest.main()
