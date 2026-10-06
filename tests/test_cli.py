import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from hamllm import cli


class CliTests(unittest.TestCase):
    def test_help_has_only_local_model_commands(self):
        text = cli.build_parser().format_help()
        for command in ("run", "models", "doctor", "eval", "resolve", "mcp"):
            self.assertIn(command, text)
        for retired in ("gmail", "mail", "bridge", "oauth"):
            self.assertNotIn(retired, text.lower())

    @patch("hamllm.cli.OllamaClient")
    def test_run_prints_local_response(self, client_type):
        client_type.return_value.installed.return_value = {"gpt-oss:20b": "sha"}
        client_type.return_value.generate.return_value = "answer"
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(["run", "hello"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "answer\n")
        options = client_type.return_value.generate.call_args.kwargs["options"]
        self.assertIn("num_ctx", options)

    @patch("hamllm.cli.OllamaClient")
    def test_doctor_fails_when_selected_model_is_missing(self, client_type):
        client = MagicMock()
        client.version.return_value = "0.11.0"
        client.installed.return_value = {"qwen3.6:27b": "sha"}
        client_type.return_value = client
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(["doctor", "--model", "gpt-oss:20b"])
        self.assertEqual(result, 1)
        self.assertIn("not an installed model", output.getvalue())


class DoctorAliasTests(unittest.TestCase):
    @patch("hamllm.cli.profiles.load")
    @patch("hamllm.cli.OllamaClient")
    def test_doctor_resolves_an_alias_default(self, client_type, load):
        client = client_type.return_value
        client.version.return_value = "0.11.0"
        client.installed.return_value = {"gemma4:12b": "sha"}
        load.return_value = {"gemma4:12b": {"ready": True, "digest": "sha", "evaluated_at": "t",
                                           "categories": {"tools": 1.0, "safety": 1.0, "coding": 1.0}}}
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli.main(["doctor", "--model", "code"])
        self.assertEqual(result, 0)
        self.assertIn("code -> gemma4:12b", output.getvalue())


class TimeoutDefaultTests(unittest.TestCase):
    """Regression: argparse shares parent actions, so mcp's 120s default once leaked into every command."""

    def timeout_used(self, argv, env=None):
        with patch.dict("os.environ", env or {}, clear=False), patch("hamllm.cli.OllamaClient") as client_type:
            client_type.return_value.installed.return_value = {}
            with patch("hamllm.mcp.serve", return_value=0), redirect_stdout(io.StringIO()):
                cli.main(argv)
        return client_type.call_args.args[1]

    def test_commands_default_to_300_but_mcp_to_120(self):
        clean = {"HAMLLM_TIMEOUT": "", "HAMLLM_MCP_TIMEOUT": ""}
        self.assertEqual(self.timeout_used(["models"], clean), 300.0)
        self.assertEqual(self.timeout_used(["mcp"], clean), 120.0)

    def test_explicit_flag_and_environment_win(self):
        self.assertEqual(self.timeout_used(["models", "--timeout", "7"]), 7.0)
        self.assertEqual(self.timeout_used(["mcp", "--timeout", "9"]), 9.0)
        self.assertEqual(self.timeout_used(["models"], {"HAMLLM_TIMEOUT": "45"}), 45.0)
        self.assertEqual(self.timeout_used(["mcp"], {"HAMLLM_MCP_TIMEOUT": "30"}), 30.0)


if __name__ == "__main__":
    unittest.main()
