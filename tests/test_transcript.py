"""Transcript source, offline, against a synthetic Antigravity data directory.

The fixture reproduces properties observed in real transcripts on 2026-09-25:
lines in completion order, call_mcp_tool with JSON-encoded and plain argument values,
large outputs saved to steps/<n>/output.txt, and a non-DONE step present in the .db
but absent from the transcript.
"""

import json
import os
import sqlite3
import time
from pathlib import Path

from ag_trace import cli

CID = "11111111-2222-3333-4444-555555555555"


def mcp(server, tool, encoded):
    enc = (lambda v: json.dumps(v)) if encoded else (lambda v: v)
    return {"name": "call_mcp_tool", "args": {"ServerName": enc(server), "ToolName": enc(tool),
                                              "Arguments": {"q": "gpu"}}}


def rows_fixture():
    t = "2026-09-11T23:55:{:02d}Z"
    return [  # written in completion order: step 1 (the request) after its results 2 and 3
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": t.format(0),
         "content": "<USER_REQUEST>\nWhat do my notes say?\n</USER_REQUEST>\n<META>x</META>"},
        {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": t.format(2), "content": "Created At: x\nCompleted At: x\nFound 3 notes"},
        {"step_index": 3, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": t.format(2), "content": "Created At: x\nThe output was large and was "
         f"saved to: file:///C:/Users/u/.gemini/antigravity/brain/{CID}/.system_generated/"
         "steps/3/output.txt"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": t.format(1),
         "tool_calls": [mcp("obsidian", "search_simple", encoded=True),
                        mcp("ollama-delegate", "index_search", encoded=False)]},
        {"step_index": 4, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": t.format(4), "content": "<USER_REQUEST>list models</USER_REQUEST>"},
        {"step_index": 5, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": t.format(5), "tool_calls": [
             {"name": "run_command", "args": {"CommandLine": '"dir | more"', "Cwd": "d:\\x"}}]},
    ]


def make_home(root, rows=None, db_extra=(), db=True, full=True, short=True, outputs=None):
    home = Path(root) / "antigravity"
    logs = home / "brain" / CID / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    rows = rows_fixture() if rows is None else rows
    text = "".join(json.dumps(r) + "\n" for r in rows)
    if full:
        (logs / "transcript_full.jsonl").write_text(text, encoding="utf-8")
    if short:
        (logs / "transcript.jsonl").write_text(text, encoding="utf-8")
    for n, body in (outputs if outputs is not None else {3: "big output " * 100}).items():
        p = home / "brain" / CID / ".system_generated" / "steps" / str(n) / "output.txt"
        p.parent.mkdir(parents=True)
        p.write_text(body, encoding="utf-8")
    if db:
        (home / "conversations").mkdir()
        con = sqlite3.connect(home / "conversations" / f"{CID}.db")
        con.execute("CREATE TABLE steps (idx integer primary key, step_type integer, "
                    "status integer)")
        idx = sorted({r["step_index"] for r in rows} | set(db_extra))
        con.executemany("INSERT INTO steps VALUES (?, 132, ?)",
                        [(i, 7 if i in db_extra else 3) for i in idx])
        con.commit()
        con.close()
    return home


def run(argv):
    try:
        cli.main(argv)
    except SystemExit as e:
        return e.code or 0
    return 0


def cap(home, out, *extra):
    return run(["capture", CID, "--ag-home", str(home), "--out", str(out), *extra])


def the_capture(out):
    (d,) = [p for p in Path(out).glob("*/*") if p.is_dir()]
    return d, json.loads((d / "manifest.json").read_text(encoding="utf-8"))


def jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- completeness

def test_complete_capture(tmp_path):
    home = make_home(tmp_path)
    assert cap(home, tmp_path / "out") == 0
    d, m = the_capture(tmp_path / "out")
    assert m["completeness"] == "COMPLETE" and m["source"] == "transcript"
    assert m["cross_check"]["db_steps"] == 6
    assert m["cross_check"]["in_step_order"] is False
    raw = (home / "brain" / CID / ".system_generated" / "logs" / "transcript_full.jsonl")
    assert (d / "evidence" / "transcript_full.jsonl").read_bytes() == raw.read_bytes()


def test_step_absent_from_transcript_but_in_db_is_short(tmp_path):
    home = make_home(tmp_path, db_extra=[6])
    assert cap(home, tmp_path / "out") == 3
    d, m = the_capture(tmp_path / "out")
    assert m["completeness"].startswith("SHORT (6/7")
    assert m["cross_check"]["absent_from_transcript"] == [
        {"step_index": 6, "db_step_type": 132, "db_status": 7}]
    assert "db_status': 7" in (d / "derived" / "summary.md").read_text(encoding="utf-8")


def test_gap_in_step_index_is_short_even_without_db(tmp_path):
    rows = [r for r in rows_fixture() if r["step_index"] != 2]
    home = make_home(tmp_path, rows=rows, db=False)
    assert cap(home, tmp_path / "out") == 3
    _, m = the_capture(tmp_path / "out")
    assert m["completeness"].startswith("SHORT") and "[2]" in m["completeness"]


def test_no_db_is_unverified(tmp_path):
    home = make_home(tmp_path, db=False)
    assert cap(home, tmp_path / "out") == 3
    _, m = the_capture(tmp_path / "out")
    assert m["completeness"].startswith("UNVERIFIED")


def test_duplicate_step_index_is_invalid(tmp_path):
    rows = rows_fixture() + [rows_fixture()[0]]
    home = make_home(tmp_path, rows=rows)
    assert cap(home, tmp_path / "out") == 3
    _, m = the_capture(tmp_path / "out")
    assert m["completeness"].startswith("INVALID")


def test_db_read_does_not_touch_live_db(tmp_path):
    home = make_home(tmp_path)
    db = home / "conversations" / f"{CID}.db"
    before = db.read_bytes(), db.stat().st_mtime_ns
    cap(home, tmp_path / "out")
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before
    assert not Path(str(db) + "-wal").exists()


# ---------------------------------------------------------------- refusals

def test_truncated_only_is_refused_and_writes_nothing(tmp_path):
    home = make_home(tmp_path, full=False)
    assert cap(home, tmp_path / "out") == 2
    assert not (tmp_path / "out").exists()


def test_truncated_only_accepted_when_asked_and_flagged(tmp_path):
    home = make_home(tmp_path, full=False)
    assert cap(home, tmp_path / "out", "--allow-truncated") == 3
    d, m = the_capture(tmp_path / "out")
    assert m["completeness"].startswith("TRUNCATED")
    assert (d / "evidence" / "transcript.jsonl").is_file()


def test_empty_transcript_writes_nothing(tmp_path):
    home = make_home(tmp_path, rows=[], db=False)
    assert cap(home, tmp_path / "out") == 2
    assert not (tmp_path / "out").exists()


def test_malformed_line_writes_nothing(tmp_path):
    home = make_home(tmp_path)
    f = home / "brain" / CID / ".system_generated" / "logs" / "transcript_full.jsonl"
    f.write_text(f.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    assert cap(home, tmp_path / "out") == 2
    assert not (tmp_path / "out").exists()


def test_unknown_id_writes_nothing(tmp_path):
    home = make_home(tmp_path)
    assert run(["capture", "nope", "--ag-home", str(home), "--out", str(tmp_path / "o")]) == 2
    assert not (tmp_path / "o").exists()


# ---------------------------------------------------------------- derived views

def test_rows_in_step_order_with_turns(tmp_path):
    home = make_home(tmp_path)
    cap(home, tmp_path / "out")
    d, _ = the_capture(tmp_path / "out")
    steps = jsonl(d / "derived" / "steps.jsonl")
    assert [s["i"] for s in steps] == [0, 1, 2, 3, 4, 5]
    assert [s["turn"] for s in steps] == [1, 1, 1, 1, 2, 2]
    assert steps[0]["label"] == "What do my notes say?"


def test_mcp_calls_resolved_for_encoded_and_plain_args(tmp_path):
    home = make_home(tmp_path)
    cap(home, tmp_path / "out")
    d, _ = the_capture(tmp_path / "out")
    calls = jsonl(d / "derived" / "calls.jsonl")
    assert [c["tool"] for c in calls] == ["mcp:obsidian/search_simple",
                                          "mcp:ollama-delegate/index_search", "run_command"]
    assert [c["turn"] for c in calls] == [1, 1, 2]
    assert calls[2]["args"]["CommandLine"] == "dir | more"  # JSON-encoded value decoded
    summary = (d / "derived" / "summary.md").read_text(encoding="utf-8")
    assert "- `obsidian`: 1" in summary and "- `ollama-delegate`: 1" in summary


def test_large_output_captured_and_linked(tmp_path):
    home = make_home(tmp_path)
    cap(home, tmp_path / "out")
    d, m = the_capture(tmp_path / "out")
    assert "steps/3/output.txt" in m["evidence"]
    step3 = [s for s in jsonl(d / "derived" / "steps.jsonl") if s["i"] == 3][0]
    assert step3["output_file"] == "steps/3/output.txt"


def test_referenced_output_missing_is_marked(tmp_path):
    home = make_home(tmp_path, outputs={})
    cap(home, tmp_path / "out")
    d, _ = the_capture(tmp_path / "out")
    step3 = [s for s in jsonl(d / "derived" / "steps.jsonl") if s["i"] == 3][0]
    assert step3["output_file"].endswith("(NOT CAPTURED)")


# ---------------------------------------------------------------- integrity

def test_verify_detects_altered_and_unlisted_files(tmp_path):
    home = make_home(tmp_path)
    cap(home, tmp_path / "out")
    d, _ = the_capture(tmp_path / "out")
    assert run(["verify", str(d)]) == 0
    extra = d / "evidence" / "steps" / "9" / "output.txt"
    extra.parent.mkdir()
    extra.write_text("planted", encoding="utf-8")
    assert run(["verify", str(d)]) == 2
    extra.unlink()
    with open(d / "evidence" / "steps" / "3" / "output.txt", "ab") as f:
        f.write(b"!")
    assert run(["verify", str(d)]) == 2
    assert run(["derive", str(d)]) == 2


def test_derive_is_reproducible(tmp_path):
    home = make_home(tmp_path)
    cap(home, tmp_path / "out")
    d, _ = the_capture(tmp_path / "out")
    names = ("steps.jsonl", "calls.jsonl", "summary.md")
    before = [(d / "derived" / n).read_bytes() for n in names]
    assert run(["derive", str(d)]) == 0
    assert [(d / "derived" / n).read_bytes() for n in names] == before


# ---------------------------------------------------------------- selection

def test_latest_is_most_recently_modified(tmp_path, capsys):
    home = make_home(tmp_path)
    other = home / "brain" / "older" / ".system_generated" / "logs"
    other.mkdir(parents=True)
    (other / "transcript_full.jsonl").write_text(
        json.dumps(rows_fixture()[0]) + "\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(other / "transcript_full.jsonl", (old, old))
    assert run(["capture", "latest", "--ag-home", str(home), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / CID).is_dir()
    assert run(["list", "--ag-home", str(home)]) == 0
    out = capsys.readouterr().out
    assert out.index(CID) < out.index("older")
