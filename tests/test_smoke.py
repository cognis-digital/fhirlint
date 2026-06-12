"""Smoke tests for FHIRLINT. No network. Runs against the bundled demo."""

import json
import os
import sys
import subprocess


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fhirlint import (  # noqa: E402
    lint_text, lint_file, has_errors, summarize, TOOL_NAME, TOOL_VERSION,
)

DEMO = os.path.join(
    os.path.dirname(__file__), "..", "demos", "01-basic", "bundle.json"
)


def test_metadata():
    assert TOOL_NAME == "fhirlint"
    assert isinstance(TOOL_VERSION, str) and TOOL_VERSION


def test_demo_file_has_expected_errors():
    findings = lint_file(DEMO)
    assert has_errors(findings)
    codes = {f.code for f in findings}
    msgs = " ".join(f.message for f in findings)

    # bad gender code
    assert "bad-code" in codes
    assert "gender" in msgs
    # bad birthDate (date primitive)
    assert "bad-primitive" in codes
    assert "birthDate" in msgs
    # bad id (space)
    assert "bad-id" in codes
    # observation status not in value set
    assert "status" in msgs
    # observation missing required code
    assert "required-missing" in codes


def test_findings_have_line_numbers():
    findings = lint_file(DEMO)
    # gender error should resolve to a real source line
    gender = [f for f in findings if "gender" in f.path]
    assert gender
    assert gender[0].line > 0


def test_clean_resource_passes():
    clean = json.dumps({
        "resourceType": "Patient",
        "id": "pat-1",
        "gender": "female",
        "birthDate": "1985-12-02",
    })
    findings = lint_text(clean)
    assert not has_errors(findings)
    assert summarize(findings)["error"] == 0


def test_invalid_json_reports_parse_error():
    findings = lint_text('{"resourceType": "Patient", }')
    assert has_errors(findings)
    assert any(f.code == "json-parse" for f in findings)


def test_unknown_resource_type():
    findings = lint_text('{"resourceType": "Patientz"}')
    assert any(f.code == "unknown-resourceType" for f in findings)


def test_missing_resource_type():
    findings = lint_text('{"id": "x"}')
    assert any(f.code == "missing-resourceType" for f in findings)


def test_bundle_bad_type():
    findings = lint_text(json.dumps({
        "resourceType": "Bundle", "type": "not-a-type",
    }))
    assert any(f.code == "bad-code" and "Bundle.type" in f.path
               for f in findings)


def test_required_status_and_code_for_observation():
    findings = lint_text(json.dumps({"resourceType": "Observation"}))
    missing = {f.path for f in findings if f.code == "required-missing"}
    assert any(p.endswith(".status") for p in missing)
    assert any(p.endswith(".code") for p in missing)


def test_cli_json_format_and_exit_code():
    proc = subprocess.run(
        [sys.executable, "-m", "fhirlint", "validate", DEMO, "--format", "json"],
        capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    assert proc.returncode == 1  # errors present -> CI gate fails
    payload = json.loads(proc.stdout)
    assert payload["tool"] == "fhirlint"
    assert payload["ok"] is False
    assert payload["files"][0]["summary"]["error"] >= 5


def test_cli_version():
    proc = subprocess.run(
        [sys.executable, "-m", "fhirlint", "--version"],
        capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    assert proc.returncode == 0
    assert "fhirlint" in proc.stdout
