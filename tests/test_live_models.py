"""Live capability tests against a real Ollama. Skipped unless HAMLLM_LIVE=1.

    HAMLLM_LIVE=1 HAMLLM_MODEL=gpt-oss:20b python -m pytest tests/test_live_models.py -v

A failure here means the local model cannot reliably do that class of work.
For repeat-run pass rates and a ready / not-ready verdict use `hamllm eval`.
"""

import os

import pytest

from hamllm.evals import CASES, run_case
from hamllm.cli import DEFAULT_MODEL
from hamllm.ollama import OllamaClient, OllamaError

pytestmark = pytest.mark.skipif(
    os.environ.get("HAMLLM_LIVE") != "1", reason="set HAMLLM_LIVE=1 to test a real local model"
)

MODEL = os.environ.get("HAMLLM_MODEL", DEFAULT_MODEL)


@pytest.fixture(scope="module")
def client():
    client = OllamaClient.from_environment()
    try:
        installed = client.models()
    except OllamaError as exc:
        pytest.fail(f"Ollama unreachable: {exc}")
    if MODEL not in installed:
        pytest.fail(f"model {MODEL!r} not installed (have: {installed})")
    return client


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.category}-{c.name}")
def test_model_can_field_request(client, case):
    result = run_case(client, MODEL, case, reasoning=os.environ.get("HAMLLM_REASONING") or None)
    assert result.passed, f"{case.description}: {result.reason}"
