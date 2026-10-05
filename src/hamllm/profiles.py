"""Capability profiles and aliases.

An eval run is saved per model. An alias such as ``code`` names the categories a
model must have passed, and resolves to the best installed model that did, so
clients stop hard-coding tags and never get a model that failed the work.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

DEFAULT_THRESHOLD = 0.8

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


def load(path: Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads((path or profiles_path()).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_report(report: dict[str, Any], path: Path | None = None) -> Path:
    """Merge one ``evals.report`` into the profile store (atomic replace)."""
    target = path or profiles_path()
    profiles = load(target)
    profiles[report["model"]] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ready": report["ready"],
        "threshold": report["threshold"],
        "repeats": report.get("repeats"),
        "num_ctx": report.get("num_ctx"),
        "median_seconds": report.get("median_seconds"),
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


def _score(profile: dict[str, Any], required: tuple[str, ...]) -> tuple[float, float]:
    rates = profile["categories"]
    mean = sum(rates[c] for c in required) / len(required)
    return (-mean, profile.get("median_seconds") or float("inf"))


def resolve(
    name: str,
    installed: list[str],
    profiles: dict[str, dict[str, Any]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    """Resolve a tag, ``default`` or an alias to an installed model tag."""
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
        if model in profiles and qualifies(profiles[model], required, threshold)
    ]
    if not candidates:
        raise ResolutionError(
            f"no installed model has passed {', '.join(required)} at {threshold:.0%}; "
            f"run `hamllm eval --save --model TAG` to profile one"
        )
    return min(candidates, key=lambda item: (*_score(item[1], required), item[0]))[0]
