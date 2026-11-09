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
        load.return_value = {"gemma4:12b": {"suite_version": cli.profiles.PROFILE_SUITE_VERSION,
                                           "ready": True, "digest": "sha", "evaluated_at": "t",
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


class ValidationTests(unittest.TestCase):
    def test_numeric_cli_limits_reject_invalid_values(self):
        for argv in (
            ["run", "--num-ctx", "0", "x"],
            ["run", "--timeout", "0", "x"],
            ["eval", "--repeats", "0"],
            ["eval", "--threshold", "1.1"],
            ["resolve", "fast", "--threshold", "-0.1"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                cli.main(argv)

    @patch("hamllm.cli.OllamaClient")
    def test_bad_context_environment_fails_cleanly(self, client_type):
        client_type.return_value.installed.return_value = {"gpt-oss:20b": "sha"}
        with patch.dict("os.environ", {"HAMLLM_NUM_CTX": "bogus"}, clear=False):
            with self.assertRaises(SystemExit):
                cli.main(["run", "hello"])

    @patch("hamllm.mcp.serve", return_value=0)
    @patch("hamllm.cli.OllamaClient")
    def test_mcp_uses_shorter_keepalive_and_usage_log_from_environment(self, client_type, serve):
        with patch.dict(
            "os.environ",
            {"HAMLLM_MCP_KEEP_ALIVE": "7m", "HAMLLM_USAGE_LOG": "/tmp/hamllm-usage-test.jsonl"},
            clear=False,
        ):
            self.assertEqual(cli.main(["mcp"]), 0)
        server = serve.call_args.args[0]
        self.assertEqual(server.keep_alive, "7m")
        self.assertEqual(str(server.usage_log), "/tmp/hamllm-usage-test.jsonl")


class EnvironmentValidationTests(unittest.TestCase):
    @patch("hamllm.cli.OllamaClient")
    def test_timeout_environment_must_be_positive_and_finite(self, client_type):
        client_type.return_value.installed.return_value = {}
        for value in ("0", "-1", "nan", "inf", "garbage"):
            with self.subTest(value=value), patch.dict(
                "os.environ", {"HAMLLM_TIMEOUT": value}, clear=False
            ), self.assertRaises(SystemExit):
                cli.main(["models"])

    @patch("hamllm.mcp.serve", return_value=0)
    @patch("hamllm.cli.OllamaClient")
    def test_mcp_timeout_environment_must_be_positive_and_finite(self, client_type, serve):
        for value in ("0", "nan", "garbage"):
            with self.subTest(value=value), patch.dict(
                "os.environ", {"HAMLLM_MCP_TIMEOUT": value}, clear=False
            ), self.assertRaises(SystemExit):
                cli.main(["mcp"])
