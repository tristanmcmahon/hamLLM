import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from hamllm import cli


class CliTests(unittest.TestCase):
    def test_help_has_only_local_model_commands(self):
        text = cli.build_parser().format_help()
        for command in ("run", "chat", "models", "doctor"):
            self.assertIn(command, text)
        for retired in ("gmail", "mail", "bridge", "oauth"):
            self.assertNotIn(retired, text.lower())

    @patch("hamllm.cli.OllamaClient")
    def test_run_prints_local_response(self, client_type):
        client_type.return_value.generate.return_value = "answer"
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(["run", "hello"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "answer\n")

    @patch("hamllm.cli.OllamaClient")
    def test_doctor_fails_when_selected_model_is_missing(self, client_type):
        client = MagicMock()
        client.version.return_value = "0.11.0"
        client.models.return_value = ["qwen3.6:27b"]
        client_type.return_value = client
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(["doctor", "--model", "gpt-oss:20b"])
        self.assertEqual(result, 1)
        self.assertIn("not installed", output.getvalue())

    @patch("hamllm.cli.OllamaClient")
    def test_chat_uses_content_helper(self, client_type):
        client_type.return_value.chat_content.return_value = "reply"
        with patch("builtins.input", side_effect=["hello", "/exit"]):
            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(["chat", "--model", "gpt-oss:20b"])
        self.assertEqual(result, 0)
        self.assertIn("gpt-oss:20b> reply", output.getvalue())


if __name__ == "__main__":
    unittest.main()
