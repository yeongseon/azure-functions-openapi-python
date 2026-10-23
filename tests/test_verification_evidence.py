"""Offline contracts for the saved verification evidence boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_report_renders_saved_json_without_running_a_lane(tmp_path: Path) -> None:
    # Given no results and an isolated working directory.
    runner = Path(__file__).resolve().parents[1] / "tools" / "verification.py"
    # When requesting a report, no test process should be started.
    result = subprocess.run(
        [sys.executable, str(runner), "report"], cwd=tmp_path, capture_output=True, text=True
    )
    # Then absence of saved evidence is explicit and non-successful.
    assert result.returncode == 1
    assert "No saved" in result.stdout
    assert not (tmp_path / "test-results").exists()


@pytest.mark.parametrize(
    ("cases", "exit_code", "status"),
    [
        ("", 0, "INCOMPLETE"),
        ("<testcase><skipped/></testcase>", 0, "INCOMPLETE"),
        ("<testcase><failure/></testcase>", 1, "FAIL"),
        ("<testcase/>", 0, "PASS"),
    ],
)
def test_junit_classifies_execution_fail_closed(
    tmp_path: Path, cases: str, exit_code: int, status: str
) -> None:
    from tools.verification_evidence import collect

    # Given actual JUnit cases, not an optimistic process exit alone.
    (tmp_path / "junit.xml").write_text(f"<testsuite>{cases}</testsuite>")
    # When collecting evidence.
    summary = collect(tmp_path, ["pytest"], exit_code)
    # Then zero/all-skipped cases cannot pass.
    assert summary.status == status


@pytest.mark.parametrize(
    "secret",
    [
        "AccountKey=VERYSECRET;",
        "SharedAccessSignature=VERYSECRET;",
        "code=VERYSECRET&x=1",
        "x-functions-key: VERYSECRET",
        "Authorization: Bearer VERYSECRET",
        "password=VERYSECRET",
        "token=VERYSECRET",
        "AzureWebJobsStorage=VERYSECRET",
    ],
)
def test_secrets_are_redacted_from_persisted_evidence(tmp_path: Path, secret: str) -> None:
    from tools.verification_evidence import collect, save

    # Given secret-bearing logs and XML attributes/text.
    (tmp_path / "junit.xml").write_text(
        "<testsuite><testcase><system-out>"
        + secret.replace("&", "&amp;")
        + "</system-out></testcase></testsuite>"
    )
    (tmp_path / "output.log").write_text(secret)
    # When saving all evidence.
    save(tmp_path, collect(tmp_path, ["pytest", secret], 0))
    # Then persisted evidence contains no credential value.
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "VERYSECRET" not in path.read_text()


def test_saved_summary_has_versioned_schema_and_supporting_paths(tmp_path: Path) -> None:
    from tools.verification_evidence import collect, save

    # Given one executed test and coverage.
    (tmp_path / "junit.xml").write_text("<testsuite><testcase/></testsuite>")
    (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.99"/>')
    # When saving a lane.
    save(tmp_path, collect(tmp_path, ["pytest"], 0))
    data = json.loads((tmp_path / "summary.json").read_text())
    # Then consumers can identify the contract and its proof.
    assert data["schema_version"] == 1
    assert (data["selected"], data["passed"], data["failed"], data["skipped"]) == (1, 1, 0, 0)
    assert data["coverage"] == 0.99
    assert str(tmp_path / "junit.xml") in data["supporting_files"]
    assert (tmp_path / "environment.json").exists()


def test_redaction_preserves_json_syntax(tmp_path: Path) -> None:
    from tools.verification_evidence import Summary, save

    summary = Summary(1, "test", ("Authorization: Bearer VERYSECRET",), 1, 1, 0, 0, "PASS", 0)
    save(tmp_path, summary)
    data = json.loads((tmp_path / "summary.json").read_text())
    assert "VERYSECRET" not in str(data)


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ('{"Authorization": "Bearer CANARY_a1"}', "CANARY_a1"),
        ("{'Authorization': 'Bearer CANARY_a2'}", "CANARY_a2"),
        ("Authorization: Bearer CANARY_a3", "CANARY_a3"),
        ("Authorization: Basic CANARY_a4==", "CANARY_a4"),
        ("authorization=SharedKey acct:CANARY_a5", "CANARY_a5"),
        ("Proxy-Authorization: Bearer CANARY_a6", "CANARY_a6"),
        ('{"password": "alpha CANARY_b1 beta"}', "CANARY_b1"),
        ('{"token": "with \\"escaped\\" CANARY_b2"}', "CANARY_b2"),
        ("password=CANARY_b3&x=1", "CANARY_b3"),
        (
            "connection_string=Endpoint=sb://ns/;SharedAccessKeyName=Root;SharedAccessKey=CANARY_c1",
            "CANARY_c1",
        ),
        (
            "DefaultEndpointsProtocol=https;AccountName=a;AccountKey=CANARY_c2;EndpointSuffix=x",
            "CANARY_c2",
        ),
        ("InstrumentationKey=CANARY_c3;IngestionEndpoint=https://x/", "CANARY_c3"),
        ("https://user:CANARY_d1@example.test/path", "CANARY_d1"),
        ("GET /api?code=CANARY_d2&x=1", "CANARY_d2"),
        ('<failure message="Authorization: Bearer CANARY_e1">x</failure>', "CANARY_e1"),
    ],
)
def test_redact_masks_every_credential_shape(text: str, leaked: str) -> None:
    from tools.verification_evidence import redact

    assert leaked not in redact(text)


@pytest.mark.parametrize(
    "text",
    [
        '{"Authorization": "Bearer CANARY_f1", "ok": true}',
        '{"password": "alpha beta", "n": 1}',
        '<failure message="Authorization: Bearer CANARY_f2">text</failure>',
    ],
)
def test_redact_keeps_json_and_xml_well_formed(text: str) -> None:
    import xml.etree.ElementTree as ET

    from tools.verification_evidence import redact

    redacted = redact(text)
    if text.startswith("{"):
        json.loads(redacted)
    else:
        ET.fromstring(redacted)


def test_redact_leaves_ordinary_text_and_names_alone() -> None:
    from tools.verification_evidence import redact

    text = "token_count=3 author=ada SharedAccessKeyName=Root status: ok"
    assert redact(text) == text


def test_known_environment_secret_is_replaced_whole_before_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.verification_evidence import redact

    monkeypatch.setenv("MY_API_TOKEN", "pre;fix&CANARY_g1 value")
    assert "CANARY_g1" not in redact("seen pre;fix&CANARY_g1 value here")
    assert "CANARY_g1" not in redact('{"x": "pre;fix&CANARY_g1 value"}')


def test_nested_secret_fields_are_redacted_before_json_is_written(tmp_path: Path) -> None:
    from tools.verification_evidence import Summary, save

    summary = Summary(
        1, "test", ("pytest", 'Authorization: "Bearer CANARY_h1"'), 1, 1, 0, 0, "PASS", 0
    )
    save(tmp_path, summary)
    text = (tmp_path / "summary.json").read_text()
    assert "CANARY_h1" not in text
    assert json.loads(text)["lane"] == "test"


def test_save_preserves_binary_assets_and_does_not_follow_symlinks(tmp_path: Path) -> None:
    from tools.verification_evidence import Summary, save

    png = b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary"
    (tmp_path / "chart.png").write_bytes(png)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.log"
    outside.write_text("password=CANARY_i1")
    (tmp_path / "link.log").symlink_to(outside)

    save(tmp_path, Summary(1, "test", ("pytest",), 1, 1, 0, 0, "PASS", 0))

    assert (tmp_path / "chart.png").read_bytes() == png
    assert outside.read_text() == "password=CANARY_i1"


def test_structured_json_evidence_stays_valid_when_a_value_is_not_a_string(tmp_path: Path) -> None:
    from tools.verification_evidence import Summary, save

    (tmp_path / "extra.json").write_text('{"password": 12345, "name": "x"}')
    save(tmp_path, Summary(1, "test", ("pytest",), 1, 1, 0, 0, "PASS", 0))
    assert json.loads((tmp_path / "extra.json").read_text())["name"] == "x"
