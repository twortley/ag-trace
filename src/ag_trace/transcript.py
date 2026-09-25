"""Offline source: the transcript Antigravity writes to disk for every conversation.

Layout observed on Antigravity (Windows, 2026-09-25), per conversation id:
    <ag_home>/brain/<id>/.system_generated/logs/transcript_full.jsonl   one JSON object per step
    <ag_home>/brain/<id>/.system_generated/logs/transcript.jsonl        same, content cut at ~4 KB
    <ag_home>/brain/<id>/.system_generated/steps/<n>/output.txt         large tool outputs
    <ag_home>/conversations/<id>.db             SQLite, `steps` table (protobuf payloads)

Observed properties that shape this module:
- transcript.jsonl truncates content at ~4 KB (`truncated_fields`). transcript_full.jsonl is
  used; the short one only with --allow-truncated, and the capture is then marked TRUNCATED.
  Older conversations have only the short one.
- Lines are written in completion order, not step order: a response that requested tool
  calls can appear after the results. Derived views sort by step_index; evidence is kept
  as written.
- A step whose status is not DONE can be absent from the transcript while present in the
  .db (seen: a run_command result with db status 7). So the step count is cross-checked
  against the .db, and absent steps are listed with their db type, status and error text.
  The .db files are captured as evidence too (see db.py).
No Antigravity process is needed, so past conversations can be captured too.
"""

import json
import os
from pathlib import Path

from ag_trace import db as dbmod
from ag_trace.evidence import CaptureError

TRANSCRIPT = "transcript_full.jsonl"
TRUNCATED = "transcript.jsonl"


def ag_home(arg=None):
    return Path(arg or os.environ.get("AG_HOME") or Path.home() / ".gemini" / "antigravity")


def _sysgen(home, cid):
    return home / "brain" / cid / ".system_generated"


def parse_rows(data):
    rows = []
    for n, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as e:
            raise CaptureError(f"{TRANSCRIPT} line {n} is not JSON: {e}") from e
    return rows


def user_request(content):
    """The typed request, without the metadata Antigravity wraps around it."""
    if "<USER_REQUEST>" in content:
        return content.split("<USER_REQUEST>", 1)[1].split("</USER_REQUEST>", 1)[0].strip()
    return content.strip()


def transcripts(home, include_truncated=False):
    """[(cascade_id, path)] newest first by file modification time. The full transcript
    is preferred; with include_truncated, conversations that only have the truncated
    one are included too, so none is silently left out of a listing."""
    found = {}
    names = (TRANSCRIPT, TRUNCATED) if include_truncated else (TRANSCRIPT,)
    for name in names:
        for p in (home / "brain").glob(f"*/.system_generated/logs/{name}"):
            found.setdefault(p.parents[2].name, p)
    return sorted(found.items(), key=lambda x: x[1].stat().st_mtime, reverse=True)


def list_local(home):
    out = []
    for cid, p in transcripts(home, include_truncated=True):
        try:
            rows = parse_rows(p.read_bytes())
        except CaptureError:
            rows = []
        req = next((user_request(r.get("content", "")) for r in rows
                    if r.get("type") == "USER_INPUT"), "")
        calls = sum(len(r.get("tool_calls") or []) for r in rows)
        out.append({"cascade_id": cid, "steps": len(rows), "tool_calls": calls,
                    "truncated": p.name == TRUNCATED,
                    "first": rows[0].get("created_at") if rows else None,
                    "last": rows[-1].get("created_at") if rows else None,
                    "request": req.replace("\n", " ")})
    return out


def capture_transcript(home, cid, allow_truncated=False):
    """Read one conversation. Returns (files, detail). Raises CaptureError."""
    if cid == "latest":
        found = transcripts(home)
        if not found:
            raise CaptureError(f"no {TRANSCRIPT} under {home / 'brain'}")
        cid = found[0][0]
    sg = _sysgen(home, cid)
    path = sg / "logs" / TRANSCRIPT
    truncated = False
    if not path.is_file():
        short = sg / "logs" / TRUNCATED
        if not short.is_file():
            raise CaptureError(f"no transcript for {cid} under {sg / 'logs'}")
        if not allow_truncated:
            raise CaptureError(f"only the truncated {TRUNCATED} exists for {cid}; "
                               "re-run with --allow-truncated to capture it marked TRUNCATED")
        path, truncated = short, True
    data = path.read_bytes()
    rows = parse_rows(data)
    if not rows:
        raise CaptureError(f"{path.name} for {cid} is empty - nothing written")

    files = {path.name: data}
    for out in sorted((sg / "steps").glob("*/output.txt")):
        files[f"steps/{out.parent.name}/output.txt"] = out.read_bytes()

    indices = [r.get("step_index") for r in rows]
    present = {i for i in indices if isinstance(i, int)}
    duplicates = sorted({i for i in present if indices.count(i) > 1})
    gaps = sorted(set(range(max(present) + 1)) - present) if present else []
    files.update(dbmod.read_files(home, cid))
    analysis, why = dbmod.analyse(files, cid)
    db = analysis["steps"] if analysis else None
    absent = sorted(set(db) - present) if db else gaps
    absent_detail = [{"step_index": i, **db[i]} for i in absent if db and i in db]
    if duplicates or len(present) != len(rows):
        completeness = "INVALID (duplicate or non-integer step_index)"
    elif absent:
        n = len(db) if db else max(present) + 1
        completeness = f"SHORT ({len(rows)}/{n}; absent steps {absent[:10]})"
    elif truncated:
        completeness = "TRUNCATED (content cut at ~4 KB)"
    elif db is None:
        completeness = f"UNVERIFIED ({why})"
    else:
        completeness = "COMPLETE"
    req = next((user_request(r.get("content", "")) for r in rows
                if r.get("type") == "USER_INPUT"), "")
    detail = {
        "cascade_id": cid,
        "title": req.splitlines()[0][:120] if req else None,
        "steps_expected": len(db) if db else None,
        "steps_received": len(rows),
        "completeness": completeness,
        "transcript_file": path.name,
        "skills_available": analysis["skills_available"] if analysis else None,
        "skills_list_from_gen_idx": analysis["skills_gen_idx"] if analysis else None,
        "cross_check": {"db_steps": len(db) if db else None, "db_note": why,
                        "in_step_order": indices == sorted(indices),
                        "absent_from_transcript": absent_detail or absent},
        "first_step_at": rows[0].get("created_at"),
        "last_step_at": rows[-1].get("created_at"),
        "source_path": str(path),
    }
    return files, detail
