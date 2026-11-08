"""Edit only hamLLM's entry in Zed's JSONC user settings.

Zed permits comments and trailing commas. Parse their structure, then splice the
smallest relevant span so unrelated settings retain their exact text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class SettingsError(ValueError):
    """Settings cannot be edited without risking unrelated configuration."""


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    value: str | None = None


@dataclass(frozen=True)
class Member:
    name: str
    key: Token
    value: Node
    comma: Token | None


@dataclass(frozen=True)
class Node:
    kind: str
    start: int
    end: int
    members: tuple[Member, ...] = ()


_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")


def _tokens(text: str) -> list[Token]:
    result: list[Token] = []
    pos = 0
    if text.startswith("\ufeff"):
        pos = 1
    while pos < len(text):
        char = text[pos]
        if char in " \t\r\n":
            pos += 1
        elif text.startswith("//", pos):
            end = text.find("\n", pos + 2)
            pos = len(text) if end < 0 else end
        elif text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            if end < 0:
                raise SettingsError("unterminated JSONC comment")
            pos = end + 2
        elif char == '"':
            try:
                value, end = json.JSONDecoder().raw_decode(text, pos)
            except json.JSONDecodeError as exc:
                raise SettingsError(f"invalid JSONC string: {exc.msg}") from exc
            if not isinstance(value, str):
                raise SettingsError("invalid JSONC string")
            result.append(Token("string", pos, end, value))
            pos = end
        elif char in "{}[]:,":
            result.append(Token(char, pos, pos + 1))
            pos += 1
        else:
            match = _NUMBER.match(text, pos)
            if match:
                end = match.end()
                result.append(Token("scalar", pos, end))
                pos = end
                continue
            keyword = next((word for word in ("true", "false", "null") if text.startswith(word, pos)), None)
            if keyword is None:
                raise SettingsError(f"unexpected JSONC character at offset {pos}")
            result.append(Token("scalar", pos, pos + len(keyword)))
            pos += len(keyword)
    return result


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def peek(self, kind: str) -> bool:
        return self.index < len(self.tokens) and self.tokens[self.index].kind == kind

    def take(self, kind: str | None = None) -> Token:
        if self.index >= len(self.tokens):
            raise SettingsError("unexpected end of JSONC settings")
        token = self.tokens[self.index]
        if kind is not None and token.kind != kind:
            raise SettingsError(f"expected {kind!r} at offset {token.start}")
        self.index += 1
        return token

    def value(self, depth: int = 0) -> Node:
        if depth > 128:
            raise SettingsError("JSONC settings are too deeply nested")
        if self.peek("{"):
            start = self.take("{")
            members: list[Member] = []
            while not self.peek("}"):
                key = self.take("string")
                self.take(":")
                value = self.value(depth + 1)
                comma = self.take(",") if self.peek(",") else None
                members.append(Member(key.value or "", key, value, comma))
                if comma is None:
                    break
            end = self.take("}")
            return Node("object", start.start, end.end, tuple(members))
        if self.peek("["):
            start = self.take("[")
            while not self.peek("]"):
                self.value(depth + 1)
                if not self.peek(","):
                    break
                self.take(",")
            return Node("array", start.start, self.take("]").end)
        token = self.take()
        if token.kind not in {"string", "scalar"}:
            raise SettingsError(f"expected a JSONC value at offset {token.start}")
        return Node(token.kind, token.start, token.end)


def parse_document(text: str) -> Node:
    parser = _Parser(_tokens(text))
    root = parser.value()
    if root.kind != "object" or parser.index != len(parser.tokens):
        raise SettingsError("Zed settings must contain one JSONC object")
    return root


def _member(node: Node, name: str) -> Member | None:
    matches = [member for member in node.members if member.name == name]
    if len(matches) > 1:
        raise SettingsError(f"duplicate {name!r} entries; refusing to choose one")
    return matches[0] if matches else None


def _insert(text: str, node: Node, name: str, value: str) -> str:
    # Insert first, leaving every existing member (and its comments) untouched.
    line_start = text.rfind("\n", 0, node.start) + 1
    base = re.match(r"[ \t]*", text[line_start:node.start]).group()
    indent = base + "  "
    newline = "\r\n" if "\r\n" in text else "\n"
    field = f"{json.dumps(name)}: {value}"
    suffix = "," if node.members else ""
    after = text[node.start + 1 : node.end - 1]
    # An inline object needs a line break before its next existing member.
    separator = newline + indent if node.members and after and not after[0].isspace() else ""
    closing = newline + base if not node.members and not after else ""
    return text[: node.start + 1] + newline + indent + field + suffix + separator + closing + text[node.start + 1 :]


def _remove(text: str, node: Node, target: Member) -> str:
    if target.comma is not None:
        if node.members[0] == target and not text[node.start + 1 : target.key.start].strip():
            # Undo a first-member insertion without leaving a blank line behind.
            return text[: node.start + 1] + text[target.comma.end :]
        return text[: target.key.start] + text[target.comma.end :]
    index = node.members.index(target)
    if index:
        previous = node.members[index - 1]
        if previous.comma is None:
            raise SettingsError("invalid JSONC member separator")
        return text[: previous.comma.start] + text[previous.comma.end : target.key.start] + text[target.value.end :]
    if not text[node.start + 1 : target.key.start].strip():
        return text[: node.start + 1] + text[target.value.end :]
    return text[: target.key.start] + text[target.value.end :]


def render(text: str | None, *, install: bool, model: str, host: str | None) -> str | None:
    if text is None:
        if not install:
            return None
        text = "{}\n"
    root = parse_document(text)
    servers = _member(root, "context_servers")
    entry = {"command": "hamllm", "args": ["mcp"], "env": {"HAMLLM_MODEL": model}}
    if host:
        entry["env"]["HAMLLM_HOST"] = host
    value = json.dumps(entry, ensure_ascii=False)

    if servers is None:
        changed = _insert(text, root, "context_servers", "{\"hamllm\": " + value + "}") if install else text
    else:
        if servers.value.kind != "object":
            raise SettingsError("context_servers is not an object")
        hamllm = _member(servers.value, "hamllm")
        if hamllm is None:
            changed = _insert(text, servers.value, "hamllm", value) if install else text
        elif install:
            changed = text[: hamllm.value.start] + value + text[hamllm.value.end :]
        else:
            changed = _remove(text, servers.value, hamllm)
    parse_document(changed)
    return changed


def edit(path: Path, *, install: bool, model: str, host: str | None, dry_run: bool) -> str:
    if path.is_symlink() or path.exists() and not path.is_file():
        raise SettingsError(f"refusing to edit non-regular settings file: {path}")
    original = path.read_text(encoding="utf-8") if path.exists() else None
    changed = render(original, install=install, model=model, host=host)
    if changed == original:
        return "unchanged"
    if dry_run:
        return "would update" if install else "would remove hamllm"

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if original is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.name}.hamllm-backup-{stamp}-{os.getpid()}")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(original)

    fd, temporary = tempfile.mkstemp(prefix=".hamllm-settings-", dir=path.parent)
    try:
        if path.exists():
            os.fchmod(fd, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(changed or "")
        # Zed may save settings while the installer is preparing its replacement.
        if (path.read_text(encoding="utf-8") if path.exists() else None) != original:
            raise SettingsError("settings changed during edit; retry the installer")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return "updated" if install else "removed hamllm"


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage hamLLM's Zed JSONC context server entry")
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--model", default="code")
    parser.add_argument("--host")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        outcome = edit(args.path, install=args.action == "install", model=args.model, host=args.host, dry_run=args.dry_run)
    except (SettingsError, OSError, UnicodeError) as exc:
        parser.exit(1, f"Zed settings unchanged: {exc}\n")
    print(f"Zed settings: {outcome}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
