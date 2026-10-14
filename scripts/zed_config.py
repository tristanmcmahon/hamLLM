#!/usr/bin/env python3
"""Add (or remove) hamLLM's MCP server in Zed's settings.json without disturbing the rest of it.

Zed's settings.json is JSONC (comments, trailing commas), so it cannot be round-tripped through
`json`. This script parses it with a small span-tracking JSONC parser and edits only the text it
needs to: it replaces or inserts one entry under "context_servers", keeps everything else
byte-for-byte, writes a timestamped backup first, and refuses to write a file it can no longer parse.

    scripts/zed_config.py --dry-run               show the diff, change nothing
    scripts/zed_config.py                         add/update the entry
    scripts/zed_config.py --remove                remove it
    scripts/zed_config.py --legacy                nested {"command": {"path", "args"}} form for older Zed

Settings path: --settings, else $ZED_SETTINGS, else ${XDG_CONFIG_HOME:-~/.config}/zed/settings.json.
Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SERVER_NAME = "hamllm"
SECTION = "context_servers"


class ParseError(ValueError):
    pass


@dataclass
class Member:
    key: str
    key_start: int
    value: Node
    end: int  # end of the value


@dataclass
class Node:
    kind: str  # object | array | string | literal
    start: int
    end: int
    members: list[Member] = field(default_factory=list)  # objects only
    text: str = ""

    def member(self, key: str) -> Member | None:
        return next((m for m in self.members if m.key == key), None)


class Parser:
    """Minimal JSONC parser that records the source span of every value."""

    def __init__(self, text: str) -> None:
        self.t = text
        self.i = 0

    def fail(self, message: str) -> ParseError:
        line = self.t.count("\n", 0, self.i) + 1
        return ParseError(f"{message} (line {line})")

    def skip(self) -> None:
        t = self.t
        while self.i < len(t):
            c = t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif t.startswith("//", self.i):
                nl = t.find("\n", self.i)
                self.i = len(t) if nl == -1 else nl
            elif t.startswith("/*", self.i):
                close = t.find("*/", self.i + 2)
                if close == -1:
                    raise self.fail("unterminated comment")
                self.i = close + 2
            else:
                return

    def string(self) -> Node:
        start = self.i
        self.i += 1
        while self.i < len(self.t):
            c = self.t[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                return Node("string", start, self.i, text=json.loads(self.t[start : self.i]))
            if c == "\n":
                break
            self.i += 1
        raise self.fail("unterminated string")

    def value(self) -> Node:
        self.skip()
        if self.i >= len(self.t):
            raise self.fail("unexpected end of file")
        c = self.t[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c == '"':
            return self.string()
        start = self.i
        while self.i < len(self.t) and self.t[self.i] not in ",}] \t\r\n/":
            self.i += 1
        literal = self.t[start : self.i]
        if not literal:
            raise self.fail(f"unexpected character {c!r}")
        try:
            json.loads(literal)
        except json.JSONDecodeError:
            raise self.fail(f"invalid value {literal!r}") from None
        return Node("literal", start, self.i, text=literal)

    def obj(self) -> Node:
        node = Node("object", self.i, self.i)
        self.i += 1
        while True:
            self.skip()
            if self.i >= len(self.t):
                raise self.fail("unterminated object")
            if self.t[self.i] == "}":
                self.i += 1
                node.end = self.i
                return node
            if self.t[self.i] != '"':
                raise self.fail("expected a quoted key")
            key = self.string()
            self.skip()
            if self.i >= len(self.t) or self.t[self.i] != ":":
                raise self.fail("expected ':'")
            self.i += 1
            value = self.value()
            node.members.append(Member(key.text, key.start, value, value.end))
            self.skip()
            if self.i < len(self.t) and self.t[self.i] == ",":
                self.i += 1
            elif self.i < len(self.t) and self.t[self.i] != "}":
                raise self.fail("expected ',' or '}'")

    def arr(self) -> Node:
        node = Node("array", self.i, self.i)
        self.i += 1
        while True:
            self.skip()
            if self.i >= len(self.t):
                raise self.fail("unterminated array")
            if self.t[self.i] == "]":
                self.i += 1
                node.end = self.i
                return node
            self.value()
            self.skip()
            if self.i < len(self.t) and self.t[self.i] == ",":
                self.i += 1
            elif self.i < len(self.t) and self.t[self.i] != "]":
                raise self.fail("expected ',' or ']'")


def parse(text: str) -> Node:
    parser = Parser(text.lstrip("﻿"))
    if text.startswith("﻿"):
        raise ParseError("file starts with a byte-order mark; remove it first")
    root = parser.value()
    if root.kind != "object":
        raise ParseError("settings.json must contain a JSON object")
    parser.skip()
    if parser.i != len(text):
        raise ParseError("unexpected content after the top-level object")
    return root


def to_python(text: str, node: Node) -> Any:
    if node.kind == "object":
        return {m.key: to_python(text, m.value) for m in node.members}
    if node.kind == "string":
        return node.text
    if node.kind == "literal":
        return json.loads(node.text)
    # arrays: re-parse the slice (rare in what we check)
    inner = text[node.start : node.end]
    return json.loads(_strip_jsonc(inner))


def _strip_jsonc(text: str) -> str:
    """Drop comments and trailing commas (string-aware) so json.loads can read a JSONC slice."""
    out, i, in_str = [], 0, False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else len(text)
            continue
        elif text.startswith("/*", i):
            i = text.find("*/", i) + 2
            continue
        else:
            out.append(c)
        i += 1
    import re

    return re.sub(r",(\s*[\]}])", r"\1", "".join(out))


# --- editing ---------------------------------------------------------------------------------


def line_indent(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = start
    while end < len(text) and text[end] in " \t":
        end += 1
    return text[start:end]


def render(entry: dict[str, Any], indent: str, one_line: bool) -> str:
    if one_line:
        return json.dumps(entry)
    body = json.dumps(entry, indent=2)
    return body.replace("\n", "\n" + indent)


def next_significant(text: str, pos: int) -> int:
    p = Parser(text)
    p.i = pos
    p.skip()
    return p.i


def insert_member(text: str, obj: Node, key: str, value: dict[str, Any]) -> str:
    if not obj.members:
        close = obj.end - 1
        if "\n" not in text[obj.start : obj.end]:
            return text[: obj.start + 1] + f" {json.dumps(key)}: {json.dumps(value)} " + text[close:]
        base = line_indent(text, obj.start)
        member = f'{base}  {json.dumps(key)}: {render(value, base + "  ", False)}'
        return text[: obj.start + 1] + "\n" + member + "\n" + base + text[close:]

    last = obj.members[-1]
    after = next_significant(text, last.end)
    has_comma = after < len(text) and text[after] == ","
    # If the closing brace shares a line with the last entry (`{"a": 1}` or `...,}`), insert
    # inline; otherwise add a new line after the last entry.
    if "\n" not in text[last.end : obj.end]:
        member = f"{json.dumps(key)}: {json.dumps(value)}"
        if has_comma:
            return text[: after + 1] + f" {member}," + text[after + 1 :]
        return text[: last.end] + f", {member}" + text[last.end :]

    indent = line_indent(text, last.key_start)
    member = f"{indent}{json.dumps(key)}: {render(value, indent, False)}"
    anchor = after + 1 if has_comma else last.end
    eol = text.find("\n", anchor)
    eol = len(text) if eol == -1 else eol  # keep any same-line comment with the previous entry
    out = text[:anchor]
    if not has_comma:
        out += ","
    out += text[anchor:eol] + "\n" + member + ("," if has_comma else "") + text[eol:]
    return out


def upsert(text: str, entry: dict[str, Any]) -> str:
    if not text.strip():
        return json.dumps({SECTION: {SERVER_NAME: entry}}, indent=2) + "\n"
    root = parse(text)
    section = root.member(SECTION)
    if section is None:
        return insert_member(text, root, SECTION, {SERVER_NAME: entry})
    if section.value.kind != "object":
        raise ParseError(f'"{SECTION}" exists but is not an object')
    existing = section.value.member(SERVER_NAME)
    if existing is not None:
        indent = line_indent(text, existing.key_start)
        one_line = "\n" not in text[existing.value.start : existing.value.end]
        return text[: existing.value.start] + render(entry, indent, one_line) + text[existing.value.end :]
    return insert_member(text, section.value, SERVER_NAME, entry)


def remove(text: str, key_path: tuple[str, str] = (SECTION, SERVER_NAME)) -> str:
    if not text.strip():
        return text
    root = parse(text)
    section = root.member(key_path[0])
    if section is None or section.value.kind != "object":
        return text
    members = section.value.members
    target = next((m for m in members if m.key == key_path[1]), None)
    if target is None:
        return text
    start, end = target.key_start, target.end
    after = next_significant(text, end)
    if after < len(text) and text[after] == ",":
        end = after + 1
    elif len(members) > 1 and members[0] is not target:
        prev = members[members.index(target) - 1]
        comma = next_significant(text, prev.end)
        text = text[:comma] + text[comma + 1 :]
        start, end = start - 1, end - 1
    # swallow the whole line when nothing else is on it
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    if not text[line_start:start].strip() and not text[end:line_end].strip():
        start, end = line_start, min(line_end + 1, len(text))
    return text[:start] + text[end:]


# --- command line ----------------------------------------------------------------------------


def settings_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("ZED_SETTINGS"):
        return Path(os.environ["ZED_SETTINGS"]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "zed" / "settings.json"


def build_entry(command: str, model: str, host: str | None, legacy: bool) -> dict[str, Any]:
    env = {"HAMLLM_MODEL": model, **({"HAMLLM_HOST": host} if host else {})}
    if legacy:
        return {"command": {"path": command, "args": ["mcp"], "env": env}}
    return {"command": command, "args": ["mcp"], "env": env}


def verify(text: str, expect: dict[str, Any] | None) -> None:
    """The edited text must still parse and contain exactly what we meant to write."""
    root = parse(text)
    section = root.member(SECTION)
    found = None
    if section is not None and section.value.kind == "object":
        member = section.value.member(SERVER_NAME)
        found = to_python(text, member.value) if member else None
    if found != expect:
        raise ParseError(f"internal check failed: expected {expect!r}, found {found!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", help="path to Zed's settings.json")
    ap.add_argument("--command", default=shutil.which("hamllm") or str(Path.home() / ".local/bin/hamllm"))
    ap.add_argument("--model", default="code", help="HAMLLM_MODEL for the server (default: the 'code' alias)")
    ap.add_argument("--host", default=os.environ.get("HAMLLM_HOST"), help="HAMLLM_HOST for the server")
    ap.add_argument("--legacy", action="store_true", help="older nested command form")
    ap.add_argument("--remove", action="store_true", help="remove the hamllm entry")
    ap.add_argument("--dry-run", action="store_true", help="show the diff and change nothing")
    args = ap.parse_args(argv)

    path = settings_path(args.settings)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    entry = None if args.remove else build_entry(args.command, args.model, args.host, args.legacy)
    try:
        updated = remove(original) if args.remove else upsert(original, entry)  # type: ignore[arg-type]
        if updated.strip():
            verify(updated, entry)
    except ParseError as exc:
        print(f"zed_config: {path}: {exc}; nothing was changed", file=sys.stderr)
        return 1

    if updated == original:
        print(f"{path}: already {'without' if args.remove else 'up to date with'} the {SERVER_NAME} server")
        return 0
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(True), updated.splitlines(True), f"{path} (before)", f"{path} (after)"
        )
    )
    if args.dry_run:
        print(diff or f"(would create {path})")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"backup: {backup}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    print(f"{path}: {'removed' if args.remove else 'updated'} the {SERVER_NAME} server")
    print(diff, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
