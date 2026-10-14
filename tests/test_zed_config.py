"""scripts/zed_config.py: edits Zed's JSONC settings.json in place without disturbing the rest."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "zed_config.py"
spec = importlib.util.spec_from_file_location("zed_config", SCRIPT)
zc = importlib.util.module_from_spec(spec)
sys.modules["zed_config"] = zc  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(zc)

ENTRY = zc.build_entry("/home/me/.local/bin/hamllm", "code", None, legacy=False)


def loads(text):
    return json.loads(zc._strip_jsonc(text))


def test_empty_or_missing_file_gets_a_fresh_settings_object():
    out = zc.upsert("", ENTRY)
    assert loads(out) == {"context_servers": {"hamllm": ENTRY}}


def test_adds_the_section_to_realistic_jsonc_and_keeps_every_other_byte():
    original = '''// Zed settings
{
  "theme": "One Dark", // my theme
  /* fonts */
  "buffer_font_size": 15,
  "language_models": {
    "ollama": { "api_url": "http://helix:11434" }, // not a comment: it is inside a string above
  },
}
'''
    out = zc.upsert(original, ENTRY)
    assert loads(out)["context_servers"]["hamllm"] == ENTRY
    assert loads(out)["language_models"]["ollama"]["api_url"] == "http://helix:11434"
    for fragment in ("// Zed settings", "// my theme", "/* fonts */", '"buffer_font_size": 15,'):
        assert fragment in out
    zc.verify(out, ENTRY)


def test_adds_alongside_other_servers_with_correct_commas_with_and_without_trailing_commas():
    no_trailing = '{\n  "context_servers": {\n    "github": { "command": "gh-mcp" }\n  }\n}\n'
    out = zc.upsert(no_trailing, ENTRY)
    servers = loads(out)["context_servers"]
    assert set(servers) == {"github", "hamllm"} and servers["github"] == {"command": "gh-mcp"}

    trailing = '{\n  "context_servers": {\n    "github": { "command": "gh-mcp" },\n  },\n}\n'
    out = zc.upsert(trailing, ENTRY)
    assert set(loads(out)["context_servers"]) == {"github", "hamllm"}
    assert out.count(",\n  },") == 1  # trailing-comma style preserved


def test_a_same_line_comment_stays_with_the_entry_it_belongs_to():
    text = '{\n  "context_servers": {\n    "github": { "command": "gh" } // work account\n  }\n}\n'
    out = zc.upsert(text, ENTRY)
    line = next(ln for ln in out.splitlines() if "work account" in ln)
    assert '"github"' in line and line.rstrip().endswith("// work account")
    assert set(loads(out)["context_servers"]) == {"github", "hamllm"}


def test_updating_is_idempotent_and_replaces_a_stale_entry():
    stale = '{"context_servers": {"hamllm": {"command": "/old/path", "args": ["mcp"]}, "other": {"command": "x"}}}'
    once = zc.upsert(stale, ENTRY)
    assert loads(once)["context_servers"]["hamllm"] == ENTRY
    assert loads(once)["context_servers"]["other"] == {"command": "x"}
    assert zc.upsert(once, ENTRY) == once


def test_empty_and_single_line_containers():
    assert loads(zc.upsert('{"context_servers": {}}', ENTRY))["context_servers"] == {"hamllm": ENTRY}
    assert loads(zc.upsert("{}", ENTRY))["context_servers"] == {"hamllm": ENTRY}
    assert loads(zc.upsert('{"a": 1}', ENTRY))["a"] == 1


def test_strings_that_look_like_structure_do_not_confuse_the_parser():
    tricky = '{"url": "http://x // not a comment /* nor this */", "braces": "}{,", "context_servers": {}}'
    out = zc.upsert(tricky, ENTRY)
    data = loads(out)
    assert data["url"] == "http://x // not a comment /* nor this */" and data["braces"] == "}{,"
    assert data["context_servers"]["hamllm"] == ENTRY


def test_closing_brace_on_the_same_line_as_the_last_entry_does_not_corrupt_the_file():
    # Found by fuzzing: the new entry used to be inserted after the closing brace.
    text = '{"theme": 1,\n  "context_servers": {"x": {\n      "a": 1\n    }, "y": 2,}\n}\n'
    out = zc.upsert(text, ENTRY)
    assert set(loads(out)["context_servers"]) == {"x", "y", "hamllm"}
    assert loads(zc.remove(out)) == loads(text)


def test_randomised_layouts_keep_their_meaning_and_round_trip():
    import random

    def gen(depth=0):
        keys = random.sample(["a", "b", "theme", "x y", "u//rl", "}{"], random.randint(0, 4))
        multi, trailing, pad = random.random() < 0.6, random.random() < 0.4, "  " * (depth + 1)
        items = [(json.dumps(k), random.choice(["1", '"s // c"', "null", '[1,{"q":3}]',
                                                 gen(depth + 1) if depth < 2 else "2"])) for k in keys]
        if not multi:
            return "{" + ", ".join(f"{k}: {v}" for k, v in items) + ("," if trailing and items else "") + "}"
        body = "".join(
            f"{pad}{k}: {v}{',' if (i < len(items) - 1 or trailing) else ''}"
            f"{random.choice(['', '  // n', ' /* n */'])}\n"
            for i, (k, v) in enumerate(items)
        )
        return "{\n" + body + "  " * depth + "}"

    random.seed(1234)
    checked = 0
    for _ in range(400):
        top = gen()
        if random.random() < 0.6 and top != "{}":
            body = top.rstrip()[:-1].rstrip()
            sep = "" if body.endswith(("{", ",")) else ","
            top = body + sep + f'\n  "context_servers": {gen(1)}\n}}'
        try:
            before = loads(top)
        except json.JSONDecodeError:
            continue
        if not isinstance(before.get("context_servers", {}), dict):
            continue
        out = zc.upsert(top, ENTRY)
        expected = json.loads(json.dumps(before))
        expected.setdefault("context_servers", {})["hamllm"] = ENTRY
        assert loads(out) == expected, (top, out)
        assert zc.upsert(out, ENTRY) == out
        assert loads(zc.remove(out)).get("context_servers", {}) == before.get("context_servers", {}), (top, out)
        checked += 1
    assert checked > 200


@pytest.mark.parametrize("bad", ['{"a": ', "[1, 2]", '{"a": 1} trailing', '{"context_servers": 5}', "{'a': 1}"])
def test_unparseable_or_unexpected_files_are_refused(bad):
    with pytest.raises(zc.ParseError):
        zc.upsert(bad, ENTRY)


def test_remove_deletes_only_our_entry_in_every_position():
    for text in (
        '{"context_servers": {"hamllm": {"command": "x"}}}',
        '{"context_servers": {"hamllm": {"command": "x"}, "b": {"command": "y"}}}',
        '{"context_servers": {"b": {"command": "y"}, "hamllm": {"command": "x"}}}',
        '{\n  "context_servers": {\n    "a": 1,\n    "hamllm": {\n      "command": "x"\n    },\n    "b": 2,\n  },\n}\n',
    ):
        data = loads(zc.remove(text))
        assert "hamllm" not in data["context_servers"]
        assert set(data["context_servers"]) == set(loads(text)["context_servers"]) - {"hamllm"}
    assert zc.remove("{}") == "{}"  # nothing to remove: unchanged


def test_remove_after_upsert_restores_the_original_semantics():
    original = '{\n  "theme": "x", // keep\n  "context_servers": {\n    "github": { "command": "gh" }\n  }\n}\n'
    assert loads(zc.remove(zc.upsert(original, ENTRY))) == loads(original)


def test_legacy_form_nests_the_command():
    entry = zc.build_entry("/bin/hamllm", "fast", "http://helix:11434", legacy=True)
    assert entry == {"command": {"path": "/bin/hamllm", "args": ["mcp"],
                                 "env": {"HAMLLM_MODEL": "fast", "HAMLLM_HOST": "http://helix:11434"}}}


# --- the CLI: files, backups, dry-run, failure modes ------------------------------------------


def run(settings, *args):
    return zc.main(["--settings", str(settings), "--command", "/bin/hamllm", *args])


def test_cli_creates_the_file_and_parent_directories(tmp_path, capsys):
    target = tmp_path / "zed" / "settings.json"
    assert run(target) == 0
    assert loads(target.read_text())["context_servers"]["hamllm"]["args"] == ["mcp"]


def test_cli_backs_up_before_editing_and_is_a_noop_the_second_time(tmp_path, capsys):
    target = tmp_path / "settings.json"
    target.write_text('{\n  "theme": "x", // mine\n}\n')
    assert run(target) == 0
    backups = list(tmp_path.glob("settings.json.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == '{\n  "theme": "x", // mine\n}\n'
    assert "// mine" in target.read_text()
    capsys.readouterr()
    assert run(target) == 0 and "up to date" in capsys.readouterr().out
    assert len(list(tmp_path.glob("settings.json.bak-*"))) == 1  # no churn when nothing changed


def test_cli_dry_run_prints_a_diff_and_writes_nothing(tmp_path, capsys):
    target = tmp_path / "settings.json"
    target.write_text('{"theme": "x"}\n')
    assert run(target, "--dry-run") == 0
    out = capsys.readouterr().out
    assert '+    "hamllm"' in out or '"hamllm"' in out
    assert target.read_text() == '{"theme": "x"}\n' and not list(tmp_path.glob("*.bak-*"))


def test_cli_refuses_to_touch_a_file_it_cannot_parse(tmp_path, capsys):
    target = tmp_path / "settings.json"
    target.write_text('{"theme": ')
    assert run(target) == 1
    assert "nothing was changed" in capsys.readouterr().err
    assert target.read_text() == '{"theme": ' and not list(tmp_path.glob("*.bak-*"))


def test_cli_remove_and_env_override(tmp_path, monkeypatch, capsys):
    target = tmp_path / "settings.json"
    monkeypatch.setenv("ZED_SETTINGS", str(target))
    assert zc.main(["--command", "/bin/hamllm"]) == 0
    assert target.exists()
    assert zc.main(["--remove"]) == 0
    assert "hamllm" not in loads(target.read_text()).get("context_servers", {})


def test_cli_preserves_file_mode(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{}\n")
    target.chmod(0o600)
    assert run(target) == 0
    assert target.stat().st_mode & 0o777 == 0o600
