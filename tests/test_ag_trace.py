"""Offline tests. No Antigravity needed: the transport is replaced by fakes."""

import hashlib
import json
from pathlib import Path

import pytest

from ag_trace import cli

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
            raise cli.CaptureError(state["error"])
        raw = state["raw"]
        return json.loads(raw), raw

    summaries = {"cid-1": ({"summary": "Test chat", "stepCount": 4,
                            "lastModifiedTime": "2026-09-25T18:00:04Z"}, EP)}
    monkeypatch.setattr(cli, "discover", lambda: [EP])
    monkeypatch.setattr(cli, "conversations", lambda eps: {
        k: ({**s, "stepCount": state["step_count"]}, e) for k, (s, e) in summaries.items()})
    monkeypatch.setattr(cli, "call", call)
    return state


def capture_dirs(root):
    return [p for p in Path(root).glob("*/*") if p.is_dir()]


# ---------------------------------------------------------------- capture

def test_capture_complete_writes_raw_unmodified(fake_ls, tmp_path):
    assert run(["capture", "latest", "--out", str(tmp_path), "--label", "T1"]) == 0
    (d,) = capture_dirs(tmp_path)
    raw = (d / "raw.json").read_bytes()
    assert raw == FIXTURE.read_bytes()
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert m["completeness"] == "COMPLETE"
    assert m["steps_received"] == 4 and m["label"] == "T1"
    assert m["tool"] == "TOOL-P058-004" and len(m["tool_sha256"]) == 64


def test_csrf_token_never_written(fake_ls, tmp_path):
    run(["capture", "latest", "--out", str(tmp_path)])
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert CSRF.encode() not in f.read_bytes(), f.name


def test_api_failure_writes_nothing(fake_ls, tmp_path):
    fake_ls["error"] = "connection refused"
    assert run(["capture", "latest", "--out", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())


def test_zero_steps_writes_nothing(fake_ls, tmp_path):
    fake_ls["raw"] = b'{"steps": []}'
    assert run(["capture", "latest", "--out", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())


def test_missing_steps_key_writes_nothing(fake_ls, tmp_path):
    fake_ls["raw"] = b'{"messages": [1]}'
    assert run(["capture", "latest", "--out", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())


def test_short_capture_is_flagged_exit_3(fake_ls, tmp_path):
    fake_ls["step_count"] = 10
    assert run(["capture", "latest", "--out", str(tmp_path)]) == 3
    (d,) = capture_dirs(tmp_path)
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["completeness"] == "SHORT (4/10)"


# ---------------------------------------------------------------- derive

def test_every_step_becomes_a_row_including_unknown_types(fake_ls, tmp_path):
    run(["capture", "latest", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    text = (d / "steps.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["type"] for r in rows] == ["USER_INPUT", "PLANNER_RESPONSE",
                                         "SOMETHING_NEW", "ERROR_MESSAGE"]
    assert "ollama-delegate | index_search" in rows[2]["label"]
    assert rows[1]["tool_calls"][0]["name"] == "index_search"
    assert rows[3]["status"] == "ERROR" and "boom" in rows[3]["label"]


def test_long_strings_compacted_in_rows_not_in_raw(fake_ls, tmp_path):
    run(["capture", "latest", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    rows = (d / "steps.jsonl").read_text(encoding="utf-8")
    assert "y" * 300 not in rows and "<5000 chars sha256:" in rows
    assert b"y" * 5000 in (d / "raw.json").read_bytes()


def test_derive_is_reproducible(fake_ls, tmp_path):
    run(["capture", "latest", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    before = (d / "steps.jsonl").read_bytes(), (d / "steps.md").read_bytes()
    assert run(["derive", str(d)]) == 0
    assert ((d / "steps.jsonl").read_bytes(), (d / "steps.md").read_bytes()) == before


def test_derive_refuses_tampered_raw(fake_ls, tmp_path):
    run(["capture", "latest", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    with open(d / "raw.json", "ab") as f:
        f.write(b" ")
    assert run(["derive", str(d)]) == 2


def test_pipe_in_label_escaped_in_markdown(fake_ls, tmp_path):
    run(["capture", "latest", "--out", str(tmp_path)])
    (d,) = capture_dirs(tmp_path)
    md = (d / "steps.md").read_text(encoding="utf-8")
    assert "boom \\| pipe" in md


# ---------------------------------------------------------------- discovery

def test_discovery_refuses_non_windows(monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    with pytest.raises(cli.CaptureError, match="Windows-only"):
        cli.discover()
