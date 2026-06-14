"""Hardening tests — edge cases, bad input, error paths.

All tests use no network, no external dependencies.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fhirlint.core import lint_text, lint_file, has_errors, summarize  # noqa: E402


# ---------------------------------------------------------------------------
# lint_text edge cases
# ---------------------------------------------------------------------------

def test_empty_string_returns_error():
    """Empty input must produce an error finding, not crash."""
    findings = lint_text("")
    assert has_errors(findings)
    assert any(f.code == "empty-input" for f in findings)


def test_whitespace_only_string_returns_error():
    findings = lint_text("   \n\t  ")
    assert has_errors(findings)
    assert any(f.code == "empty-input" for f in findings)


def test_non_string_input_returns_error():
    """Passing None or a non-string must produce a clean error finding."""
    findings = lint_text(None)  # type: ignore[arg-type]
    assert has_errors(findings)
    assert any(f.code == "bad-input" for f in findings)


def test_non_object_json_returns_error():
    """A JSON array at root is not a FHIR resource."""
    findings = lint_text('[{"resourceType": "Patient"}]')
    assert has_errors(findings)
    assert any(f.code == "not-object" for f in findings)


def test_bundle_empty_entries_no_crash():
    """Bundle with an empty entry array must not crash."""
    data = json.dumps({"resourceType": "Bundle", "type": "collection", "entry": []})
    findings = lint_text(data)
    # No errors — an empty entry list is valid in R4
    assert not has_errors(findings)


def test_bundle_entry_without_resource_is_warning():
    """Bundle entry missing 'resource' should produce a warning, not a crash."""
    data = json.dumps({
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{}],
    })
    findings = lint_text(data)
    assert any(f.code == "entry-no-resource" for f in findings)
    assert not any(f.severity == "error" and f.code == "entry-no-resource"
                   for f in findings)


def test_summarize_returns_zero_counts_for_empty():
    """summarize() must return zero counts for an empty finding list."""
    counts = summarize([])
    assert counts["error"] == 0
    assert counts["warning"] == 0
    assert counts["info"] == 0


# ---------------------------------------------------------------------------
# lint_file edge cases
# ---------------------------------------------------------------------------

def test_missing_file_raises_file_not_found():
    """lint_file on a non-existent path must raise FileNotFoundError."""
    import pytest
    with pytest.raises(FileNotFoundError):
        lint_file("/tmp/does_not_exist_fhirlint_test_abc123.json")


def test_binary_file_returns_encoding_error():
    """A binary (non-UTF-8) file must return an encoding-error finding."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
        fh.write(b"\xff\xfe{invalid utf-8 \x80\x81}")
        tmp_path = fh.name
    try:
        findings = lint_file(tmp_path)
        assert has_errors(findings)
        assert any(f.code == "encoding-error" for f in findings)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# CLI edge cases (subprocess)
# ---------------------------------------------------------------------------

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "fhirlint", *args],
        capture_output=True, text=True, cwd=_REPO,
    )


def test_cli_no_command_returns_exit_2():
    """Running fhirlint with no subcommand should exit 2 and print help."""
    proc = _run_cli()
    assert proc.returncode == 2


def test_cli_missing_file_exits_1_and_reports_error():
    """A non-existent path should exit 1 (error finding) with a clear message."""
    proc = _run_cli("validate", "/tmp/no_such_file_xyz.json")
    assert proc.returncode == 1
    assert "file not found" in proc.stdout or "file not found" in proc.stderr


def test_cli_missing_file_json_format_exits_1():
    """Missing file in JSON format output should still exit 1 and be valid JSON."""
    proc = _run_cli("validate", "/tmp/no_such_file_xyz.json", "--format", "json")
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert any(
        f["code"] == "file-not-found"
        for entry in payload["files"]
        for f in entry["findings"]
    )


def test_cli_malformed_json_file_exits_1():
    """A file containing malformed JSON should exit 1 with a json-parse finding."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=_REPO
    ) as fh:
        fh.write('{"resourceType": "Patient", }')
        tmp_path = fh.name
    try:
        proc = _run_cli("validate", tmp_path)
        assert proc.returncode == 1
        assert "json-parse" in proc.stdout or "invalid JSON" in proc.stdout
    finally:
        os.unlink(tmp_path)


def test_cli_clean_resource_exits_0():
    """A valid Patient resource with no errors should exit 0."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=_REPO
    ) as fh:
        json.dump({"resourceType": "Patient", "id": "pat-ok"}, fh)
        tmp_path = fh.name
    try:
        proc = _run_cli("validate", tmp_path)
        assert proc.returncode == 0
    finally:
        os.unlink(tmp_path)
