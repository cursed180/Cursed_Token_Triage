from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import privacy_scrub  # noqa: E402


@pytest.fixture
def synth_patterns() -> privacy_scrub._PatternConfig:
    raw = {
        "path_patterns": [
            {
                "pattern": r"/home/(?!user\b|devuser\b|runner\b|ubuntu\b)[A-Za-z0-9_.-]+",
                "description": "operator-style /home/<user> path",
                "allowlist": [],
            },
            {
                "pattern": r"/Users/(?!user\b|runner\b)[A-Za-z0-9_.-]+",
                "description": "operator-style /Users/<user> path (macOS)",
                "allowlist": [],
            },
            {
                "pattern": r"\.claude/projects/-[A-Za-z0-9_-]+",
                "description": "real Claude Code project slug",
                "allowlist": [],
            },
        ],
        "namespace_patterns": [
            {
                "pattern": r"\bSYNTH_NS_(?!SelfRepo\b)[A-Za-z][A-Za-z0-9_]*",
                "description": "sibling-namespace project reference",
            },
            {
                "pattern": r"\bSYNTH_NAME\b",
                "description": "operator real name",
                "ignorecase": True,
            },
            {
                "pattern": r"\bsynth_handle\b",
                "description": "operator handle",
                "ignorecase": True,
            },
        ],
    }
    return privacy_scrub._PatternConfig(raw)


def test_clean_text_passes(tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig) -> None:
    """Clean text passes the full surface: path, namespace, DSN and import checks.

    Exercised with ``synth_patterns`` so the path/namespace machinery actually
    runs -- without it only the built-in DSN + import checks would fire and the
    name would overstate what is covered.
    """
    f = tmp_path / "ok.md"
    f.write_text("This is a clean README about token-triage. /home/user/myproject is fine.\n")
    assert privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns) == []


def test_flags_operator_home_path(
    tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig
) -> None:
    f = tmp_path / "leak.md"
    f.write_text("see /home/synthuser/secret/path\n")
    issues = privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns)
    assert any("operator-style /home/" in i for i in issues)


def test_flags_macos_path(tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig) -> None:
    f = tmp_path / "leak.md"
    f.write_text("see /Users/synthhnd/some/file\n")
    issues = privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns)
    assert any("operator-style /Users/" in i for i in issues)


def test_flags_real_project_slug(
    tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig
) -> None:
    f = tmp_path / "leak.md"
    f.write_text("/.claude/projects/-home-synthuser-secret-thing/abc.jsonl\n")
    issues = privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns)
    assert any("real Claude Code project slug" in i for i in issues)


def test_flags_sibling_repo_name(
    tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig
) -> None:
    f = tmp_path / "leak.md"
    f.write_text("we use SYNTH_NS_OtherProject to do X\n")
    issues = privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns)
    assert any("sibling-namespace project reference" in i for i in issues)


def test_allows_self_repo_reference(
    tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig
) -> None:
    f = tmp_path / "ok.md"
    f.write_text("SYNTH_NS_SelfRepo is fine to mention.\n")
    issues = privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns)
    assert not any("SYNTH_NS_" in i for i in issues)


def test_flags_synth_name(tmp_path: Path, synth_patterns: privacy_scrub._PatternConfig) -> None:
    f = tmp_path / "leak.md"
    f.write_text("SYNTH_NAME Consulting offers a paid audit.\n")
    issues = privacy_scrub.scan_text(f, f.read_text(), patterns=synth_patterns)
    assert any("operator real name" in i for i in issues)


def test_flags_dsn(tmp_path: Path) -> None:
    f = tmp_path / "leak.md"
    f.write_text("DATABASE_URL=postgres://user:secret@db.internal:5432/app\n")
    issues = privacy_scrub.scan_text(f, f.read_text())
    assert any("connection string" in i for i in issues)


def test_flags_network_import_in_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "token_triage"
    pkg.mkdir()
    f = pkg / "evil.py"
    f.write_text("import requests\n\nrequests.get('https://example.com')\n")
    monkeypatch.setattr(privacy_scrub, "REPO_ROOT", tmp_path)
    issues = privacy_scrub.scan_text(f, f.read_text())
    assert any("network-capable import" in i for i in issues)


@pytest.mark.parametrize(
    "code",
    [
        "import socket",
        "import socket as s",
        "import requests, json",
        "from urllib.request import urlopen",
        "from urllib import request",
        "from http import client",
        "import urllib",
        "import http",
        "import http.client",
        "from socket import socket",
    ],
)
def test_flags_known_network_import_bypasses(
    code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = tmp_path / "token_triage"
    pkg.mkdir()
    f = pkg / "evil.py"
    f.write_text(code + "\n")
    monkeypatch.setattr(privacy_scrub, "REPO_ROOT", tmp_path)
    issues = privacy_scrub.scan_text(f, f.read_text())
    assert any("network-capable import" in i for i in issues), f"missed: {code!r}"


def test_allows_safe_imports_in_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "token_triage"
    pkg.mkdir()
    f = pkg / "ok.py"
    f.write_text(
        "import json\nimport hashlib\nfrom pathlib import Path\nfrom datetime import datetime\n"
    )
    monkeypatch.setattr(privacy_scrub, "REPO_ROOT", tmp_path)
    issues = privacy_scrub.scan_text(f, f.read_text())
    assert not any("network-capable import" in i for i in issues)


def test_allows_network_import_outside_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = tmp_path / "scripts"
    pkg.mkdir()
    f = pkg / "tool.py"
    f.write_text("import requests\n")
    monkeypatch.setattr(privacy_scrub, "REPO_ROOT", tmp_path)
    issues = privacy_scrub.scan_text(f, f.read_text())
    assert not any("network-capable import" in i for i in issues)


def test_repo_passes_self_scan() -> None:
    """The repo must pass the privacy scrub. Load-bearing regression assertion.

    This runs with ``patterns=None`` -- the same way CI and the pre-commit hook
    run it, because the operator's personal path/namespace patterns live in an
    out-of-repo config that is intentionally absent here. So it asserts the repo
    is clean against the *built-in* checks only (DSN strings + network imports
    inside ``token_triage/``). The path/namespace matching machinery is covered
    separately by the ``synth_patterns`` tests above and the end-to-end
    ``test_config_from_disk_flags_planted_leak``.
    """
    issues = privacy_scrub.scan_files([REPO_ROOT])
    assert issues == [], "\n".join(issues)


def test_no_config_emits_warning(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a local config the warning is emitted to stderr but the scan proceeds.

    Hermetic: ``_config_path`` is forced to ``None`` so the result does not
    depend on whether the host running the tests happens to have a real
    ``~/.config/token-triage/`` config. Asserting the warning *text* means a
    silent regression of the message is caught -- the prior version captured
    stderr but never read it.
    """
    monkeypatch.setattr(privacy_scrub, "_config_path", lambda: None)

    cfg = privacy_scrub._pattern_config(warn=True)
    assert cfg is None

    err = capsys.readouterr().err.lower()
    assert "personal/namespace patterns are disabled" in err
    assert "token_triage_scrub_config" in err  # remediation hint is present


def test_no_config_silent_when_warn_false(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``warn=False`` suppresses the missing-config notice (library / nested use)."""
    monkeypatch.setattr(privacy_scrub, "_config_path", lambda: None)

    cfg = privacy_scrub._pattern_config(warn=False)
    assert cfg is None
    assert capsys.readouterr().err == ""


def test_config_from_disk_flags_planted_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: a JSON config on disk loads via ``_pattern_config`` and drives ``scan_files``.

    Covers the real config-loading path (``_config_path`` -> ``_load_patterns``
    -> ``_PatternConfig``) that the in-memory ``synth_patterns`` fixture skips,
    and confirms a planted leak is caught through the full file-walking pipeline.
    """
    config = tmp_path / "scrub.json"
    config.write_text(
        json.dumps(
            {
                "path_patterns": [
                    {
                        "pattern": r"/home/(?!user\b)[A-Za-z0-9_.-]+",
                        "description": "operator home path",
                        "allowlist": [],
                    }
                ],
                "namespace_patterns": [
                    {"pattern": r"\bDISKNS_[A-Za-z]+", "description": "sibling namespace"}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOKEN_TRIAGE_SCRUB_CONFIG", str(config))

    patterns = privacy_scrub._pattern_config(warn=False)
    assert patterns is not None

    scan_dir = tmp_path / "docs"
    scan_dir.mkdir()
    (scan_dir / "leak.md").write_text(
        "path /home/operator/x and ref DISKNS_Secret here\n", encoding="utf-8"
    )
    issues = privacy_scrub.scan_files([scan_dir], patterns=patterns)
    assert any("operator home path" in i for i in issues)
    assert any("sibling namespace" in i for i in issues)


def test_malformed_config_returns_none_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid-JSON config degrades to built-in-only checks (None) with a warning."""
    config = tmp_path / "scrub.json"
    config.write_text("{ this is not valid json", encoding="utf-8")
    monkeypatch.setenv("TOKEN_TRIAGE_SCRUB_CONFIG", str(config))

    patterns = privacy_scrub._pattern_config(warn=True)
    assert patterns is None
    assert "failed to load config" in capsys.readouterr().err.lower()
