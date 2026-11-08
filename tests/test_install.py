"""scripts/install.sh against stub clients and Zed settings in a throwaway HOME."""

import json
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
    for name in ("claude", "codex", "zed"):
        stub = stubs / name
        # Mimic real CLI behaviour that bit us: Claude's --env is variadic, so a bare word
        # after it (e.g. the server name) is swallowed as a KEY=VALUE and rejected.
        stub.write_text(
            f'''#!/bin/sh
echo "{name} $*" >> "$STUB_LOG"
[ "${{STUB_FAIL:-}}" = "{name}" ] && {{ echo "boom" >&2; exit 1; }}
if [ "{name}" = claude ]; then
  mode=""
  for a in "$@"; do
    case "$a" in
      --) break ;;
      --env|-e) mode=env ;;
      -*) mode="" ;;
      *) if [ "$mode" = env ]; then case "$a" in *=*) ;; *) echo "Invalid environment variable format: $a" >&2; exit 1 ;; esac; fi ;;
    esac
  done
fi
'''
        )
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


def zed_settings(env):
    return Path(env["HOME"], ".config", "zed", "settings.json")


def zed_backups(env):
    return list(zed_settings(env).parent.glob("settings.json.hamllm-backup-*"))


def test_dry_run_changes_nothing(env):
    out = install(env, "--dry-run", "--instructions").stdout
    assert "claude mcp add" in out and "codex mcp add" in out
    assert not Path(env["PREFIX"], "bin", "hamllm").exists()
    assert calls(env) == []
    assert not Path(env["HOME"], ".claude").exists()
    assert not zed_settings(env).exists()


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
    assert "Zed settings: updated" in out
    assert json.loads(zed_settings(env).read_text())["context_servers"]["hamllm"] == {
        "command": "hamllm",
        "args": ["mcp"],
        "env": {"HAMLLM_MODEL": "code", "HAMLLM_HOST": env["HAMLLM_HOST"]},
    }


def test_reinstall_is_idempotent_and_removes_before_adding(env):
    install(env)
    first = zed_settings(env).read_bytes()
    first_mtime = zed_settings(env).stat().st_mtime_ns
    install(env)
    log = calls(env)
    assert sum(c.startswith("claude mcp remove") for c in log) == 2
    assert sum(c.startswith("claude mcp add") for c in log) == 2
    assert zed_settings(env).read_bytes() == first
    assert zed_settings(env).stat().st_mtime_ns == first_mtime
    assert zed_backups(env) == []


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
    assert not zed_settings(env).exists()


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
    assert "hamllm" not in zed_settings(env).read_text()
    assert len(zed_backups(env)) == 1


def test_zed_jsonc_preserves_unrelated_settings_and_servers_with_backup(env):
    path = zed_settings(env)
    path.parent.mkdir(parents=True)
    original = '''{
  // User preference
  "theme": "dark",
  "context_servers": {
    "openclaw": { "command": "openclaw", "args": ["mcp", "serve"] }, // keep
  },
  "vim_mode": true,
}
'''
    path.write_text(original)
    install(env, "--zed")
    updated = path.read_text()
    assert '"theme": "dark"' in updated and '"vim_mode": true' in updated
    assert '"openclaw": { "command": "openclaw", "args": ["mcp", "serve"] }, // keep' in updated
    assert '"command": "hamllm"' in updated
    assert len(zed_backups(env)) == 1 and zed_backups(env)[0].read_text() == original
    assert calls(env) == []
    install(env, "--zed")
    assert path.read_text() == updated and len(zed_backups(env)) == 1
    install(env, "--uninstall", "--zed")
    assert path.read_text() == original
    assert len(zed_backups(env)) == 2
    assert not Path(env["PREFIX"], "bin", "hamllm").exists()


def test_zed_existing_entry_updates_only_its_value_and_host(env):
    path = zed_settings(env)
    path.parent.mkdir(parents=True)
    path.write_text('''{"context_servers": {"hamllm": {"old": true}, "other": {"command": "other"}}}\n''')
    custom = {**env, "HAMLLM_HOST": "http://helix:11434", "HAMLLM_MCP_MODEL": "fast"}
    install(custom, "--zed")
    text = path.read_text()
    assert '"other": {"command": "other"}' in text
    assert '"HAMLLM_MODEL": "fast"' in text and '"HAMLLM_HOST": "http://helix:11434"' in text
    install({**env, "HAMLLM_HOST": ""}, "--zed")
    assert '"HAMLLM_HOST"' not in path.read_text()
    install(env, "--uninstall", "--zed")
    assert '"other": {"command": "other"}' in path.read_text()
    assert '"hamllm"' not in path.read_text()


def test_zed_dry_run_does_not_edit_or_backup_existing_settings(env):
    path = zed_settings(env)
    path.parent.mkdir(parents=True)
    path.write_text('{"theme": "dark"}\n')
    install(env, "--zed", "--dry-run")
    assert path.read_text() == '{"theme": "dark"}\n' and not zed_backups(env)
    install(env, "--zed")
    installed = path.read_text()
    install(env, "--zed", "--uninstall", "--dry-run")
    assert path.read_text() == installed and len(zed_backups(env)) == 1


def test_existing_zed_settings_are_used_even_without_zed_on_path(env):
    path = zed_settings(env)
    path.parent.mkdir(parents=True)
    path.write_text('{"theme": "dark"}\n')
    (Path(env["PATH"].split(os.pathsep)[0]) / "zed").unlink()
    install(env)
    assert '"hamllm"' in path.read_text()
    assert '"theme": "dark"' in path.read_text()


@pytest.mark.parametrize("bad", ['{"context_servers": [1]}', '{"theme": /* broken'])
def test_zed_invalid_jsonc_fails_without_rewriting(env, bad):
    path = zed_settings(env)
    path.parent.mkdir(parents=True)
    path.write_text(bad)
    result = install(env, "--zed", check=False)
    assert result.returncode == 1 and "Zed settings unchanged" in result.stderr
    assert path.read_text() == bad and not zed_backups(env)


def test_zed_refuses_symlink_settings(env, tmp_path):
    path = zed_settings(env)
    path.parent.mkdir(parents=True)
    target = tmp_path / "target.json"
    target.write_text('{}\n')
    path.symlink_to(target)
    result = install(env, "--zed", check=False)
    assert result.returncode == 1 and "non-regular" in result.stderr
    assert target.read_text() == '{}\n' and not zed_backups(env)


def test_rejects_unknown_options(env):
    result = install(env, "--bogus", check=False)
    assert result.returncode == 2 and "unknown option" in result.stderr


def test_paths_with_spaces_work(env, tmp_path):
    prefix = tmp_path / "my prefix"
    install({**env, "PREFIX": str(prefix)}, "--no-mcp")
    out = subprocess.run([str(prefix / "bin" / "hamllm"), "--version"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, shlex.quote(out.stderr)


def test_a_failed_registration_is_reported_and_fails_the_install_but_not_the_other_client(env):
    result = install({**env, "STUB_FAIL": "claude"}, check=False)
    assert result.returncode == 1
    assert "WARN: registering with Claude Code failed" in result.stdout
    assert "claude mcp add" in result.stdout  # the manual command is printed
    assert any(c.startswith("codex mcp add") for c in calls(env))  # codex still registered
    assert Path(env["PREFIX"], "bin", "hamllm").exists()


def test_env_flag_is_not_followed_by_the_bare_server_name(env):
    install(env, "--claude")  # the stub rejects `--env K=V hamllm` like real Claude Code
