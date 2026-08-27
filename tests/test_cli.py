from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from token_triage.cli import _parse_since, build_parser, main


def test_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.format == "markdown"
    assert args.top == 10
    assert args.windows == 5
    assert args.anon is False
    assert args.force is False


@pytest.mark.parametrize("value, delta", [("7d", timedelta(days=7)), ("24h", timedelta(hours=24))])
def test_parse_since_duration(value: str, delta: timedelta) -> None:
    parsed = _parse_since(value)
    now = datetime.now(timezone.utc)
    diff = now - parsed
    # Should be within ~1 second of `delta`.
    assert abs(diff.total_seconds() - delta.total_seconds()) < 5


def test_parse_since_iso() -> None:
    parsed = _parse_since("2026-04-01T00:00:00Z")
    assert parsed == datetime(2026, 4, 1, tzinfo=timezone.utc)


def test_parse_since_rejects_bad_value() -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_since("yesterday")


def test_main_emits_markdown(synthetic_projects_dir: Path, tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "out.md"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--format",
            "markdown",
        ]
    )
    assert rc == 0
    content = out_path.read_text()
    assert "# Token Triage Report" in content
    assert "/home/user/webapp" in content


def test_main_emits_json(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "out.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    assert parsed["schema"] == "token-triage/1"
    assert parsed["totals"]["record_count"] > 0


def test_main_anon_strips_project_paths(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "out.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--format",
            "json",
            "--anon",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    project_strs = json.dumps(parsed)
    assert "/home/user/webapp" not in project_strs
    assert "/home/user/pipeline" not in project_strs
    assert "project-" in project_strs


def test_main_missing_projects_dir(tmp_path: Path, capsys) -> None:
    rc = main(["--projects-dir", str(tmp_path / "nope")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "projects directory not found" in captured.err


def test_main_rates_override(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(
        json.dumps(
            {
                "claude-opus-4-7": {
                    "input": 0.0,
                    "cache_write_5m": 0.0,
                    "cache_write_1h": 0.0,
                    "cache_read": 0.0,
                    "output": 0.0,
                }
            }
        )
    )
    out_path = tmp_path / "out.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--format",
            "json",
            "--rates",
            str(rates_path),
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    # All Opus is now free; Sonnet rates are still default.
    opus_rows = [r for r in parsed["model_breakdown"] if r["family"] == "opus"]
    for row in opus_rows:
        assert row["cost_usd"] == 0.0


def test_main_since_filters(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "out.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--format",
            "json",
            "--since",
            "2026-04-02T00:00:00Z",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    # Only the scripts project has activity on/after Apr 2 in our fixture.
    project_names = [p["project"] for p in parsed["top_projects"]]
    assert project_names == ["/home/user/scripts"]


# ---- flag-combination matrix ----


def test_main_output_refuses_overwrite_by_default(
    synthetic_projects_dir: Path, tmp_path: Path, capsys
) -> None:
    out_path = tmp_path / "report.md"
    out_path.write_text("existing")
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert out_path.read_text() == "existing"


def test_main_output_force_overwrites(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "report.md"
    out_path.write_text("existing")
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--force",
        ]
    )
    assert rc == 0
    content = out_path.read_text()
    assert "# Token Triage Report" in content
    assert content != "existing"


def test_main_since_and_output_json(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "triage.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--since",
            "2026-03-01T00:00:00Z",
            "--output",
            str(out_path),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    assert parsed["schema"] == "token-triage/1"
    assert parsed["totals"]["record_count"] > 0


def test_main_anon_and_output(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "anon.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--anon",
            "--output",
            str(out_path),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    project_strs = json.dumps(parsed)
    assert "/home/user/webapp" not in project_strs
    assert "project-" in project_strs


def test_main_rates_and_since_and_output(synthetic_projects_dir: Path, tmp_path: Path) -> None:
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(
        json.dumps(
            {
                "claude-opus-4-7": {
                    "input": 0.0,
                    "cache_write_5m": 0.0,
                    "cache_write_1h": 0.0,
                    "cache_read": 0.0,
                    "output": 0.0,
                }
            }
        )
    )
    out_path = tmp_path / "result.md"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--rates",
            str(rates_path),
            "--since",
            "2026-03-01T00:00:00Z",
            "--output",
            str(out_path),
            "--top",
            "2",
            "--windows",
            "1",
        ]
    )
    assert rc == 0
    assert "# Token Triage Report" in out_path.read_text()


def test_main_invalid_since_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--projects-dir",
                str(tmp_path),
                "--since",
                "7days",
            ]
        )
    assert exc_info.value.code == 2


def test_main_nonexistent_projects_dir(capsys) -> None:
    rc = main(["--projects-dir", "/nonexistent/path/12345"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "projects directory not found" in captured.err


def test_main_nonexistent_rates_file(tmp_path: Path, capsys) -> None:
    # Provide a valid projects-dir so the failure surface is the rates file.
    rc = main(
        [
            "--projects-dir",
            str(tmp_path),
            "--rates",
            "/nonexistent/path/rates.json",
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "failed to load rates" in captured.err


@pytest.mark.parametrize("flag,key", [("--top", "top_projects"), ("--windows", "hot_5h_windows")])
def test_main_zero_limit_is_allowed(
    flag: str, key: str, synthetic_projects_dir: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "out.json"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--output",
            str(out_path),
            "--format",
            "json",
            flag,
            "0",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text())
    assert parsed[key] == []


def test_main_force_without_output_is_harmless(synthetic_projects_dir: Path, capsys) -> None:
    """--force without --output is a no-op; stdout output is unaffected."""
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--force",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "# Token Triage Report" in captured.out


def test_main_json_to_stdout(synthetic_projects_dir: Path, capsys) -> None:
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["schema"] == "token-triage/1"


# ---- $0-meter guardrail warning (Change 3) ----


def test_main_warns_on_zero_meter_model(tmp_path: Path, capsys) -> None:
    """When a model with calls has $0 cost, a warning must be emitted to stderr."""
    proj_dir = tmp_path / "projects" / "-p-mystery"
    proj_dir.mkdir(parents=True)
    record = {
        "type": "assistant",
        "sessionId": "sess-x",
        "timestamp": "2026-04-01T10:00:00Z",
        "message": {
            "model": "totally-unknown-model",
            "role": "assistant",
            "usage": {
                "input_tokens": 500,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 200,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 0,
                },
            },
        },
    }
    (proj_dir / "session.jsonl").write_text(json.dumps(record) + "\n")
    rc = main(["--projects-dir", str(tmp_path / "projects"), "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert "totally-unknown-model" in captured.err
    assert "$0.00 cost" in captured.err


def test_main_no_warning_for_priced_models(synthetic_projects_dir: Path, capsys) -> None:
    """No $0-meter warning must appear when all models have known pricing."""
    rc = main(["--projects-dir", str(synthetic_projects_dir), "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "warning" not in captured.err.lower()


def test_main_no_false_positive_warning_with_rates_override(
    synthetic_projects_dir: Path, tmp_path: Path, capsys
) -> None:
    """Explicitly zeroed-out rates via --rates must NOT trigger the $0-meter warning.

    The warning targets unknown models (no pricing table entry), not models whose
    rates have been intentionally set to zero by the operator.  We key on
    ``lookup_rates(model, rates_table) is None``, so Opus 4.7 at $0 via override
    remains in the table and is excluded from the guardrail.
    """
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(
        json.dumps(
            {
                "claude-opus-4-7": {
                    "input": 0.0,
                    "cache_write_5m": 0.0,
                    "cache_write_1h": 0.0,
                    "cache_read": 0.0,
                    "output": 0.0,
                }
            }
        )
    )
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--format",
            "json",
            "--rates",
            str(rates_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    # Opus 4.7 is in the merged rates table (even at $0), so lookup_rates returns
    # non-None and the guardrail must NOT fire for it.
    assert "warning" not in captured.err.lower()


# ---- --strict on unpriced models (issue #1) ----


def _unpriced_projects_dir(tmp_path: Path) -> Path:
    """One project with a single call on a model no rates table knows."""
    from tests.conftest import write_session_jsonl

    root = tmp_path / "projects"
    record = {
        "type": "assistant",
        "sessionId": "s-unpriced",
        "timestamp": "2026-04-01T12:00:00Z",
        "message": {
            "model": "claude-fable-6",
            "role": "assistant",
            "usage": {
                "input_tokens": 1_000,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 500,
            },
        },
    }
    write_session_jsonl(root / "-home-user-mystery" / "01.jsonl", [record])
    return root


def test_main_warns_but_exits_zero_on_unpriced_by_default(tmp_path: Path, capsys) -> None:
    rc = main(["--projects-dir", str(_unpriced_projects_dir(tmp_path))])
    assert rc == 0
    captured = capsys.readouterr()
    assert "claude-fable-6" in captured.err
    assert "warning" in captured.err.lower()


def test_main_strict_exits_3_on_unpriced(tmp_path: Path, capsys) -> None:
    rc = main(["--projects-dir", str(_unpriced_projects_dir(tmp_path)), "--strict"])
    assert rc == 3
    captured = capsys.readouterr()
    assert "unpriced" in captured.err
    # Strict mode refuses to emit the report itself.
    assert "# Token Triage Report" not in captured.out


def test_main_strict_exits_zero_when_all_priced(
    synthetic_projects_dir: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "out.md"
    rc = main(
        [
            "--projects-dir",
            str(synthetic_projects_dir),
            "--strict",
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()


def test_main_strict_respects_rates_override(tmp_path: Path) -> None:
    """--rates that prices the unknown model must clear the --strict gate."""
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(
        json.dumps(
            {
                "claude-fable-6": {
                    "input": 12.0,
                    "cache_write_5m": 15.0,
                    "cache_write_1h": 24.0,
                    "cache_read": 1.2,
                    "output": 60.0,
                }
            }
        )
    )
    rc = main(
        [
            "--projects-dir",
            str(_unpriced_projects_dir(tmp_path)),
            "--strict",
            "--rates",
            str(rates_path),
        ]
    )
    assert rc == 0
