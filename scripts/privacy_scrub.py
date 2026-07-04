#!/usr/bin/env python3
"""Best-effort sensitive-data scan.

Run as a pre-commit hook (against staged files) and in CI (against the whole tree).
Exits non-zero on any match. Designed to catch the obvious foot-guns; it is not
a substitute for review.

Categories:

* operator-personal absolute paths (``/home/<user>``, ``/Users/<user>``,
  ``C:\\Users\\<user>``) — loaded from user config
* real Claude Code project slugs (``~/.claude/projects/<slug>``) — loaded from user config
* operator-internal repo names beyond this one — loaded from user config
* DSN / connection strings with embedded credentials — built-in
* network-import bans inside the package source — built-in; this is the testable form of
  the "no telemetry" guarantee in the README

Sensitive patterns live in ``~/.config/token-triage/scrub-patterns.json`` (or the
path given by ``TOKEN_TRIAGE_SCRUB_CONFIG``) so that real identifiers never need to
be committed to the public repo.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files allowed to mention these patterns (e.g. the scrub script itself).
ALLOWLIST_FILES = {
    "scripts/privacy_scrub.py",
    "tests/test_privacy_scrub.py",
}

# Directories never scanned.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}

# File suffixes scanned for textual patterns.
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".ini",
    ".sh",
    ".jsonl",
    ".lock",
    "",
}

# Built-in patterns that are generic enough to ship in public source.
DSN_PATTERN = re.compile(
    r"(?:postgres(?:ql)?|mysql|redis|mongodb|amqp|amqps)://[^@\s]+@[^\s'\"]+",
    re.IGNORECASE,
)

# Network imports / modules that would let token_triage/* reach the network.
# This is the testable form of the README's "no telemetry" guarantee.
#
# Caveats this regex deliberately does not cover -- string-pattern scrubs are not
# a substitute for human review, and dynamic imports (``__import__('socket')``,
# ``importlib.import_module(...)``) bypass any static check.
NETWORK_IMPORT_PATTERN = re.compile(
    r"^\s*(?:"
    # ``import foo`` / ``import foo.bar`` -- the first segment must be a banned root.
    r"import\s+(?P<imp>requests|httpx|aiohttp|urllib3|urllib|socket|http|ssl|paramiko|fabric|telnetlib)"
    r"(?:\s*,\s*\w+(?:\.\w+)*)*"  # ``import foo, bar``
    r"|"
    # ``from foo[.bar] import ...`` -- root must be banned regardless of submodule.
    r"from\s+(?P<frm>requests|httpx|aiohttp|urllib3|urllib|socket|http|ssl|paramiko|fabric|telnetlib)"
    r"(?:\.\w+)*\s+import"
    r")\b",
    re.MULTILINE,
)


def _config_path() -> Path | None:
    env = os.environ.get("TOKEN_TRIAGE_SCRUB_CONFIG")
    if env:
        p = Path(env)
        return p if p.exists() else None
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    for name in ("scrub-patterns.yaml", "scrub-patterns.yml", "scrub-patterns.json"):
        p = xdg / "token-triage" / name
        if p.exists():
            return p
    return None


def _load_patterns(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]

            return yaml.safe_load(text) or {}  # type: ignore[no-any-return]
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to parse .yaml/.yml config files. "
                "Install it or switch to a .json config."
            ) from exc
    return json.loads(text)


class _PatternConfig:
    def __init__(self, raw: dict) -> None:
        self.path_patterns: list[tuple[re.Pattern[str], str, set[str]]] = []
        for entry in raw.get("path_patterns", []):
            pat = re.compile(entry["pattern"])
            allow = set(entry.get("allowlist", []))
            self.path_patterns.append((pat, entry["description"], allow))

        self.namespace_patterns: list[tuple[re.Pattern[str], str]] = []
        for entry in raw.get("namespace_patterns", []):
            flags = 0
            if entry.get("ignorecase"):
                flags |= re.IGNORECASE
            pat = re.compile(entry["pattern"], flags)
            self.namespace_patterns.append((pat, entry["description"]))


def _pattern_config(warn: bool = True) -> _PatternConfig | None:
    path = _config_path()
    if path is None:
        if warn:
            print(
                "privacy_scrub: no config found. "
                "Personal/namespace patterns are disabled. "
                "Only built-in checks (DSN, network imports) are active. "
                "Set TOKEN_TRIAGE_SCRUB_CONFIG or create "
                "~/.config/token-triage/scrub-patterns.{json,yaml}",
                file=sys.stderr,
            )
        return None
    try:
        raw = _load_patterns(path)
    except (json.JSONDecodeError, ImportError, OSError) as exc:
        if warn:
            print(f"privacy_scrub: failed to load config {path}: {exc}", file=sys.stderr)
        return None
    return _PatternConfig(raw)


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def iter_text_files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            for child in path.rglob("*"):
                if any(part in SKIP_DIRS for part in child.parts):
                    continue
                if child.is_file() and (
                    child.suffix in TEXT_SUFFIXES
                    or child.name.lower() in {"license", "makefile", "readme"}
                ):
                    out.append(child)
        elif path.is_file():
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in TEXT_SUFFIXES or path.name.lower() in {
                "license",
                "makefile",
                "readme",
            }:
                out.append(path)
    return out


def scan_text(
    path: Path,
    text: str,
    *,
    patterns: _PatternConfig | None = None,
) -> list[str]:
    rel = relative(path)
    issues: list[str] = []

    if patterns is not None:
        for pat, desc, allowlist in patterns.path_patterns:
            if rel in ALLOWLIST_FILES or rel in allowlist:
                continue
            for m in pat.finditer(text):
                issues.append(f"{rel}: {desc}: {m.group(0)!r}")

        for pat, desc in patterns.namespace_patterns:
            if rel in ALLOWLIST_FILES:
                continue
            for m in pat.finditer(text):
                issues.append(f"{rel}: {desc}: {m.group(0)!r}")

    if rel not in ALLOWLIST_FILES:
        for m in DSN_PATTERN.finditer(text):
            issues.append(f"{rel}: connection string with embedded credentials: {m.group(0)!r}")

    # Only enforce the network-import ban inside the package source.
    if rel.startswith("token_triage/"):
        for m in NETWORK_IMPORT_PATTERN.finditer(text):
            offender = m.group("imp") or m.group("frm")
            issues.append(
                f"{rel}: network-capable import {offender!r} is forbidden inside token_triage/"
            )
    return issues


def scan_files(paths: list[Path], *, patterns: _PatternConfig | None = None) -> list[str]:
    issues: list[str] = []
    for path in iter_text_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        issues.extend(scan_text(path, text, patterns=patterns))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for personally-identifying content.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files / directories to scan (default: the repo root).",
    )
    args = parser.parse_args(argv)

    patterns = _pattern_config(warn=True)
    paths = args.paths or [REPO_ROOT]
    issues = scan_files(paths, patterns=patterns)
    if issues:
        for line in issues:
            print(line, file=sys.stderr)
        print(f"\nprivacy scrub: {len(issues)} issue(s) found.", file=sys.stderr)
        return 1
    print("privacy scrub: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
