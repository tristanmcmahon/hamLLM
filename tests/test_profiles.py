import json

import pytest

from hamllm import profiles
from hamllm.profiles import ResolutionError, resolve

GOOD = {"categories": {"basic": 1.0, "instruction": 1.0, "tools": 1.0, "safety": 1.0, "coding": 1.0}, "median_seconds": 9.0}
FAST_GOOD = {**GOOD, "median_seconds": 2.0}
NO_CODE = {"categories": {"basic": 1.0, "instruction": 1.0, "tools": 1.0, "safety": 1.0, "coding": 0.0}, "median_seconds": 1.0}


def test_installed_tag_resolves_to_itself_even_unprofiled():
    assert resolve("qwen:1b", ["qwen:1b"], {}) == "qwen:1b"


def test_alias_picks_best_qualifying_model_then_fastest():
    installed = ["a", "b", "c"]
    saved = {"a": GOOD, "b": FAST_GOOD, "c": NO_CODE}
    assert resolve("code", installed, saved) == "b"  # c is fastest but failed coding
    assert resolve("fast", installed, saved) == "c"  # coding is irrelevant to "fast"; equal scores, c quickest

def test_alias_ranks_by_score_before_speed():
    saved = {
        "slow-strong": {"categories": {"basic": 1.0, "instruction": 1.0}, "median_seconds": 30.0},
        "fast-weak": {"categories": {"basic": 0.8, "instruction": 0.8}, "median_seconds": 1.0},
    }
    assert resolve("fast", ["slow-strong", "fast-weak"], saved) == "slow-strong"


def test_alias_never_returns_unprofiled_or_uninstalled_models():
    with pytest.raises(ResolutionError, match="hamllm eval --save"):
        resolve("code", ["a"], {})
    with pytest.raises(ResolutionError):
        resolve("code", ["a"], {"ghost": GOOD})  # profiled but not installed


def test_unknown_name_lists_options():
    with pytest.raises(ResolutionError, match="aliases"):
        resolve("nonsense", ["a"], {})


def test_default_alias_follows_environment(monkeypatch):
    monkeypatch.setenv("HAMLLM_MODEL", "mine:7b")
    assert resolve("default", ["mine:7b"], {}) == "mine:7b"
    with pytest.raises(ResolutionError):
        resolve("default", ["other"], {})


def test_save_and_load_round_trip_and_merge(tmp_path):
    path = tmp_path / "state" / "profiles.json"
    report = {"model": "a", "ready": True, "threshold": 0.8, "categories": {"basic": 1.0}, "median_seconds": 1.5}
    profiles.save_report(report, path)
    profiles.save_report({**report, "model": "b", "ready": False}, path)
    loaded = profiles.load(path)
    assert set(loaded) == {"a", "b"} and loaded["a"]["ready"] is True
    assert "evaluated_at" in loaded["a"]
    assert not [p for p in path.parent.iterdir() if p.name != "profiles.json"]  # no temp litter


def test_load_tolerates_missing_and_corrupt_files(tmp_path):
    assert profiles.load(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert profiles.load(bad) == {}
    bad.write_text(json.dumps([1, 2]))
    assert profiles.load(bad) == {}


def test_digest_change_voids_a_profile():
    saved = {"a": {**GOOD, "digest": "old"}}
    assert resolve("code", ["a"], saved, digests={"a": "old"}) == "a"
    with pytest.raises(ResolutionError, match="digest"):
        resolve("code", ["a"], saved, digests={"a": "new"})
    # Profiles saved without a digest, or digests not reported, are not treated as stale.
    assert resolve("code", ["a"], {"a": GOOD}, digests={"a": "anything"}) == "a"
    assert resolve("code", ["a"], saved, digests={}) == "a"


def test_save_report_records_digest(tmp_path):
    path = tmp_path / "p.json"
    profiles.save_report({"model": "a", "ready": True, "threshold": 0.8, "categories": {}}, path, digest="sha-9")
    assert profiles.load(path)["a"]["digest"] == "sha-9"
