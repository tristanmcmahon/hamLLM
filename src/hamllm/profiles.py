"""Capability profiles and aliases.

An eval run is saved per model. An alias such as ``code`` names the categories a
model must have passed, and resolves to the best installed model that did, so
clients stop hard-coding tags and never get a model that failed the work.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

DEFAULT_THRESHOLD = 0.8
PROFILE_SUITE_VERSION = 2

ALIASES: dict[str, tuple[str, ...]] = {
    "fast": ("basic", "instruction"),
    "tools": ("tools", "safety"),
    "code": ("tools", "safety", "coding"),
}
DEFAULT_ALIAS = "default"


class ResolutionError(ValueError):
    """A model name or alias could not be resolved to an installed model."""


def profiles_path() -> Path:
    return config.state_dir() / "profiles.json"


def _valid_rate(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0.0 <= value <= 1.0


def _valid_profile(profile: Any) -> bool:
    if not isinstance(profile, dict):
        return False
    categories = profile.get("categories")
    if not isinstance(categories, dict) or not all(
        isinstance(name, str) and _valid_rate(rate) for name, rate in categories.items()
    ):
        return False
    trials = profile.get("trials")
    if trials is not None and (
        not isinstance(trials, dict)
        or not all(
            isinstance(name, str)
            and not isinstance(count, bool)
            and isinstance(count, int)
            and count >= 0
            for name, count in trials.items()
        )
    ):
        return False
    category_latency = profile.get("category_median_seconds")
    if category_latency is not None and (
        not isinstance(category_latency, dict)
        or not all(
            isinstance(name, str)
            and not isinstance(seconds, bool)
            and isinstance(seconds, (int, float))
            and math.isfinite(seconds)
            and seconds >= 0
            for name, seconds in category_latency.items()
        )
    ):
        return False
    median = profile.get("median_seconds")
    if median is not None and (
        isinstance(median, bool)
        or not isinstance(median, (int, float))
        or not math.isfinite(median)
        or median < 0
    ):
        return False
    digest = profile.get("digest")
    if digest is not None and not isinstance(digest, str):
        return False
    ready = profile.get("ready")
    if ready is not None and not isinstance(ready, bool):
        return False
    suite_version = profile.get("suite_version")
    if suite_version is not None and (
        isinstance(suite_version, bool) or not isinstance(suite_version, int) or suite_version < 1
    ):
        return False
    return True


def load(path: Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads((path or profiles_path()).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        model: profile
        for model, profile in data.items()
        if isinstance(model, str) and model and _valid_profile(profile)
    }


def save_report(report: dict[str, Any], path: Path | None = None, *, digest: str | None = None) -> Path:
    """Merge one ``evals.report`` into the profile store (atomic replace)."""
    target = path or profiles_path()
    profiles = load(target)
    profiles[report["model"]] = {
        "digest": digest or None,
        "suite_version": PROFILE_SUITE_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ready": report["ready"],
        "threshold": report["threshold"],
        "repeats": report.get("repeats"),
        "num_ctx": report.get("num_ctx"),
        "trials": report.get("trials"),
        "median_seconds": report.get("median_seconds"),
        "category_median_seconds": report.get("category_median_seconds"),
        "categories": report["categories"],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".profiles-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profiles, handle, indent=2, sort_keys=True)
        os.replace(tmp, target)
    except BaseException:
        os.unlink(tmp)
        raise
    return target


def qualifies(profile: dict[str, Any], required: tuple[str, ...], threshold: float) -> bool:
    rates = profile.get("categories") or {}
    return all(rates.get(category, 0.0) >= threshold for category in required)


def _lower_bound(rate: float, trials: int, z: float = 1.2816) -> float:
    """Wilson lower confidence bound (90% one-sided): a pass rate discounted by how little evidence is behind it."""
    if trials <= 0:
        return 0.0
    centre = rate + z * z / (2 * trials)
    margin = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials))
    return max(0.0, (centre - margin) / (1 + z * z / trials))


def _score(profile: dict[str, Any], required: tuple[str, ...]) -> tuple[float, float]:
    rates = profile["categories"]
    trials = profile.get("trials") or {}
    fallback = profile.get("repeats") or 1  # older profiles did not record trials
    mean = sum(_lower_bound(rates[c], trials.get(c, fallback)) for c in required) / len(required)
    category_latency = profile.get("category_median_seconds") or {}
    relevant = [category_latency.get(category) for category in required]
    if relevant and all(isinstance(value, (int, float)) for value in relevant):
        speed = sum(relevant) / len(relevant)
    else:
        speed = profile.get("median_seconds") or float("inf")
    return (-mean, speed)


def is_stale(profile: dict[str, Any], digest: str | None) -> bool:
    """A profile describes the weights it was measured on; a changed digest voids it."""
    return bool(digest and profile.get("digest") and profile["digest"] != digest)


def is_outdated(profile: dict[str, Any]) -> bool:
    """A changed eval suite voids old capability claims even when model weights are unchanged."""
    return profile.get("suite_version") != PROFILE_SUITE_VERSION


def resolve(
    name: str,
    installed: list[str],
    profiles: dict[str, dict[str, Any]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    digests: dict[str, str] | None = None,
) -> str:
    """Resolve a tag, ``default`` or an alias to an installed model tag.

    ``digests`` (tag -> current digest) lets resolution ignore profiles measured on
    weights that have since been replaced under the same tag.
    """
    digests = digests or {}
    if name == DEFAULT_ALIAS:
        name = config.default_model()
    if name in installed:
        return name
    required = ALIASES.get(name)
    if required is None:
        raise ResolutionError(
            f"{name!r} is not an installed model or alias "
            f"(aliases: {', '.join([DEFAULT_ALIAS, *ALIASES])}; installed: {', '.join(installed) or 'none'})"
        )
    candidates = [
        (model, profiles[model])
        for model in installed
        if model in profiles
        and qualifies(profiles[model], required, threshold)
        and not is_stale(profiles[model], digests.get(model))
        and not is_outdated(profiles[model])
    ]
    if not candidates:
        raise ResolutionError(
            f"no installed model has passed {', '.join(required)} at {threshold:.0%}; "
            f"run `hamllm eval --save --model TAG` to profile one (stale digest or older-suite profiles are ignored)"
        )
    return min(candidates, key=lambda item: (*_score(item[1], required), item[0]))[0]
