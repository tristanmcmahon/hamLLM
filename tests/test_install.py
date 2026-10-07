"""scripts/install.sh against stub claude/codex CLIs in a throwaway HOME."""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install.sh"


@pytest.fixture
def env(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("claude", "codex"):
        stub = stubs / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n')
        stub.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    return {
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "HOME": str(home),
        "PREFIX": str(home / ".local"),
        "STUB_LOG": str(tmp_path / "calls.log"),
        "HAMLLM_HOST": "http://127.0.0.1:9",  # nothing listens: doctor must only warn
        "HAMLLM_STATE_DIR": str(tmp_path / "state"),
    }


def install(env, *args, check=True):
    result = subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def calls(env):
    log = Path(env["STUB_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def test_dry_run_changes_nothing(env):
    out = install(env, "--dry-run", "--instructions").stdout
    assert "claude mcp add" in out and "codex mcp add" in out
    assert not Path(env["PREFIX"], "bin", "hamllm").exists()
    assert calls(env) == []
    assert not Path(env["HOME"], ".claude").exists()


def test_install_writes_a_working_launcher_and_registers_both_clients(env):
    out = install(env).stdout
    launcher = Path(env["PREFIX"], "bin", "hamllm")
    assert launcher.exists() and os.access(launcher, os.X_OK)
    version = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, env=env)
    assert version.stdout.startswith("hamLLM ")
    assert "OK: MCP server answers and offers ask_local" in out
    assert "WARN: Ollama not healthy" in out  # unreachable Ollama is a warning, not a failure

    log = calls(env)
    add_claude = next(c for c in log if c.startswith("claude mcp add"))
    assert "--scope user" in add_claude and "HAMLLM_MODEL=code" in add_claude
    assert f"hamllm -- {launcher} mcp" in add_claude
    assert any(c.startswith("codex mcp add") and f"hamllm -- {launcher} mcp" in c for c in log)
    assert '"context_servers"' in out or '"hamllm": { "command"' in out  # Zed snippet printed


def test_reinstall_is_idempotent_and_removes_before_adding(env):
    install(env)
    install(env)
    log = calls(env)
    assert sum(c.startswith("claude mcp remove") for c in log) == 2
    assert sum(c.startswith("claude mcp add") for c in log) == 2


def test_single_client_flag_and_host_passthrough(env):
    env = {**env, "HAMLLM_HOST": "http://helix:11434", "HAMLLM_MCP_MODEL": "fast"}
    install(env, "--claude")
    log = calls(env)
    assert not any(c.startswith("codex") for c in log)
    add = next(c for c in log if c.startswith("claude mcp add"))
    assert "HAMLLM_HOST=http://helix:11434" in add and "HAMLLM_MODEL=fast" in add


def test_no_mcp_skips_registration(env):
    install(env, "--no-mcp")
    assert calls(env) == [] and Path(env["PREFIX"], "bin", "hamllm").exists()


def test_instructions_block_is_added_once_and_preserves_existing_text(env):
    claude_md = Path(env["HOME"], ".claude", "CLAUDE.md")
    claude_md.parent.mkdir()
    claude_md.write_text("# My rules\n\nBe kind.\n")
    install(env, "--no-mcp", "--instructions")
    install(env, "--no-mcp", "--instructions")
    text = claude_md.read_text()
    assert text.startswith("# My rules\n\nBe kind.") and text.count("hamllm:begin") == 1
    assert "ask_local" in text and "not private" in text
    assert Path(env["HOME"], ".codex", "AGENTS.md").exists()


def test_uninstall_removes_everything_it_added_and_nothing_else(env):
    claude_md = Path(env["HOME"], ".claude", "CLAUDE.md")
    claude_md.parent.mkdir()
    claude_md.write_text("# My rules\n\nBe kind.\n")
    install(env, "--instructions")
    install(env, "--uninstall")
    assert not Path(env["PREFIX"], "bin", "hamllm").exists()
    assert claude_md.read_text() == "# My rules\n\nBe kind.\n"
    assert not Path(env["HOME"], ".codex", "AGENTS.md").exists()  # file we created is removed
    assert any(c.startswith("claude mcp remove") for c in calls(env))


def test_rejects_unknown_options(env):
    result = install(env, "--bogus", check=False)
    assert result.returncode == 2 and "unknown option" in result.stderr


def test_paths_with_spaces_work(env, tmp_path):
    prefix = tmp_path / "my prefix"
    install({**env, "PREFIX": str(prefix)}, "--no-mcp")
    out = subprocess.run([str(prefix / "bin" / "hamllm"), "--version"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, shlex.quote(out.stderr)
