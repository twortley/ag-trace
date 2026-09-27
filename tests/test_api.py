"""API source, offline: the LanguageServer is replaced by fakes."""

import hashlib
import json
from pathlib import Path

import pytest

from ag_trace import cli, live
from ag_trace.evidence import CaptureError

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_steps.json"
CSRF = "csrf-secret-do-not-write"
EP = {"pid": 1234, "port": 5555, "csrf": CSRF, "exe": r"C:\fake\language_server.exe"}


def run(argv):
    try:
        cli.main(argv)
    except SystemExit as e:
        return e.code or 0
    return 0


@pytest.fixture
def fake_ls(monkeypatch):
    """Fake LanguageServer. Tests set state['raw'] or state['error']."""
    state = {"raw": FIXTURE.read_bytes(), "step_count": 4, "error": None}

    def call(port, csrf, method, body, timeout=30):
        assert csrf == CSRF
        if state["error"]:
            raise CaptureError(state["error"])
        raw = state["raw"]
        return json.loads(raw), raw

    summaries = {"cid-1": ({"summary": "Test chat", "stepCount": 4,
                            "lastModifiedTime": "2026-09-25T18:00:04Z"}, EP)}
    monkeypatch.setattr(live, "discover", lambda: [EP])
    monkeypatch.setattr(live, "conversations", lambda eps: {
        k: ({**s, "stepCount": state["step_count"]}, e) for k, (s, e) in summaries.items()})
    monkeypatch.setattr(live, "call", call)
    return state


def capture_dirs(root):
    return [p for p in Path(root).glob("*/*") if p.is_dir()]


# ---------------------------------------------------------------- capture

def test_capture_complete_writes_raw_unmodified(fake_ls, tmp_path):
    argv = ["capture", "latest", "--source", "api", "--out", str(tmp_path), "--label", "T1"]
    assert run(argv) == 0
    (d,) = capture_dirs(tmp_path)
    raw = (d / "evidence" / "api_steps.json").read_bytes()
    assert raw == FIXTURE.read_bytes()
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["evidence"]["api_steps.json"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert m["completeness"] == "COMPLETE"
    assert m["steps_received"] == 4 and m["label"] == "T1"
    assert m["tool"] == "ag-trace" and len(m["tool_sha256"]) == 64


def m_tool(text):
    return json.loads(text)["tool"]


def test_manifest_names_no_private_registry_id(fake_ls, tmp_path):
    """A public tool writes its own name into every manifest, never an internal id."""
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    text = (d / "manifest.json").read_text(encoding="utf-8")
    assert m_tool(text) == "ag-trace" and "TOOL-P" not in text


def test_host_label_replaces_the_machine_name(fake_ls, tmp_path, monkeypatch):
    """Captures get attached to shared records; the host name is the user's to disclose."""
    monkeypatch.setattr("platform.node", lambda: "REAL-HOSTNAME-42")
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path), "--host-label", "ENV-7"])
    (d,) = capture_dirs(tmp_path)
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["host"] == "ENV-7"
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.suffix != ".zip":
            assert b"REAL-HOSTNAME-42" not in f.read_bytes(), f.name


def test_host_label_from_environment(fake_ls, tmp_path, monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "REAL-HOSTNAME-42")
    monkeypatch.setenv("AG_TRACE_HOST", "lab-box")
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    assert json.loads((d / "manifest.json").read_text(encoding="utf-8"))["host"] == "lab-box"


def test_host_defaults_to_the_machine_name(fake_ls, tmp_path, monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "REAL-HOSTNAME-42")
    monkeypatch.delenv("AG_TRACE_HOST", raising=False)
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["host"] == "REAL-HOSTNAME-42"


def test_csrf_token_never_written(fake_ls, tmp_path):
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert CSRF.encode() not in f.read_bytes(), f.name


def test_api_failure_writes_nothing(fake_ls, tmp_path):
    fake_ls["error"] = "connection refused"
    assert run(["capture", "latest", "--source", "api", "--out", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())


def test_zero_steps_writes_nothing(fake_ls, tmp_path):
    fake_ls["raw"] = b'{"steps": []}'
    assert run(["capture", "latest", "--source", "api", "--out", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())


def test_missing_steps_key_writes_nothing(fake_ls, tmp_path):
    fake_ls["raw"] = b'{"messages": [1]}'
    assert run(["capture", "latest", "--source", "api", "--out", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())


def test_short_capture_is_flagged_exit_3(fake_ls, tmp_path):
    fake_ls["step_count"] = 10
    assert run(["capture", "latest", "--source", "api", "--out", str(tmp_path)]) == 3
    (d,) = capture_dirs(tmp_path)
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["completeness"] == "SHORT (4/10)"


# ---------------------------------------------------------------- derive

def test_every_step_becomes_a_row_including_unknown_types(fake_ls, tmp_path):
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    text = (d / "derived" / "steps.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["type"] for r in rows] == ["USER_INPUT", "PLANNER_RESPONSE",
                                         "SOMETHING_NEW", "ERROR_MESSAGE"]
    assert "ollama-delegate | index_search" in rows[2]["label"]
    calls = (d / "derived" / "calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(calls[0])["tool"] == "index_search"
    assert rows[3]["status"] == "ERROR" and "boom" in rows[3]["label"]


def test_long_strings_compacted_in_rows_not_in_raw(fake_ls, tmp_path):
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    rows = (d / "derived" / "steps.jsonl").read_text(encoding="utf-8")
    assert "y" * 300 not in rows and "<5000 chars sha256:" in rows
    assert b"y" * 5000 in (d / "evidence" / "api_steps.json").read_bytes()


def test_derive_is_reproducible(fake_ls, tmp_path):
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    names = ("steps.jsonl", "calls.jsonl", "summary.md")
    before = [(d / "derived" / n).read_bytes() for n in names]
    assert run(["derive", str(d)]) == 0
    assert [(d / "derived" / n).read_bytes() for n in names] == before


def test_derive_refuses_tampered_raw(fake_ls, tmp_path):
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    with open(d / "evidence" / "api_steps.json", "ab") as f:
        f.write(b" ")
    assert run(["derive", str(d)]) == 2


def test_pipe_in_label_escaped_in_markdown(fake_ls, tmp_path):
    run(["capture", "latest", "--source", "api", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    md = (d / "derived" / "summary.md").read_text(encoding="utf-8")
    assert "boom \\| pipe" in md


# ---------------------------------------------------------------- discovery

def test_discovery_refuses_non_windows(monkeypatch):
    monkeypatch.setattr(live.platform, "system", lambda: "Linux")
    with pytest.raises(CaptureError, match="Windows-only"):
        live.discover()
