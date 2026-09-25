"""The per-conversation SQLite database: conversations/<id>.db (+ -wal, -shm).

Steps are stored as protobuf, which ag-trace does not decode. Three things are read
from it, all by plain SQL or by locating readable text inside a blob:

- the step index, type and status of every step - an independent count against the
  transcript, and the status of steps the transcript leaves out;
- readable text in `error_details` - e.g. "user denied permission to run command";
- the "Available skills" list in the prompt stored in `gen_metadata`, which is the
  set of skills the model was offered.

The files are captured as evidence exactly as read, then opened from a temporary copy,
so the live database is never opened.
"""

import re
import sqlite3
import tempfile
from pathlib import Path

_TEXT = re.compile(rb"[\x20-\x7e]{12,}")
_SKILLS = re.compile(rb"<skills>(.*?)</skills>", re.S)
_SKILL_LINE = re.compile(r"^- ([^\s(]+) \((.+?)\): (.*)$")


def read_files(home, cid):
    """{relative evidence path: bytes} for the db and its companions, or {}."""
    out = {}
    base = Path(home) / "conversations" / f"{cid}.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(base) + suffix)
        if p.is_file():
            out[f"db/{cid}.db{suffix}"] = p.read_bytes()
    return out


def _texts(blob, limit=3):
    if not blob:
        return []
    seen, out = set(), []
    for m in _TEXT.findall(blob):
        s = m.decode("ascii").strip()
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def parse_skills(block):
    """[{name, path, description}] from the "Available skills:" list in a <skills> block.
    Lines before that heading are Antigravity's explanation and are ignored."""
    out = []
    marker = "Available skills:"
    if marker not in block:
        return out
    for line in block.split(marker, 1)[1].splitlines():
        m = _SKILL_LINE.match(line.strip())
        if m:
            out.append({"name": m.group(1), "path": m.group(2), "description": m.group(3)})
    return out


def analyse(files, cid):
    """-> (analysis, None) or (None, reason). analysis = {"steps": {idx: {...}},
    "skills_available": [...] or None, "skills_gen_idx": int or None}"""
    main = files.get(f"db/{cid}.db")
    if main is None:
        return None, "no conversation .db"
    with tempfile.TemporaryDirectory() as tmp:
        for rel, data in files.items():
            if rel.startswith("db/"):
                (Path(tmp) / Path(rel).name).write_bytes(data)
        con = None
        try:
            con = sqlite3.connect(Path(tmp) / f"{cid}.db")
            cols = {r[1] for r in con.execute("PRAGMA table_info(steps)")}
            err = "error_details" if "error_details" in cols else "NULL"
            steps = {}
            for idx, typ, status, blob in con.execute(
                    f"SELECT idx, step_type, status, {err} FROM steps"):
                steps[idx] = {"db_step_type": typ, "db_status": status,
                              "db_error": _texts(blob)}
            skills, gen_idx = None, None
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "gen_metadata" in tables:
                for idx, blob in con.execute(
                        "SELECT idx, data FROM gen_metadata ORDER BY idx DESC"):
                    m = _SKILLS.search(blob or b"")
                    if m:
                        skills = parse_skills(m.group(1).decode("utf-8", "replace"))
                        gen_idx = idx
                        break
            return {"steps": steps, "skills_available": skills,
                    "skills_gen_idx": gen_idx}, None
        except sqlite3.Error as e:
            return None, f"db unreadable: {e}"
        finally:
            if con is not None:
                con.close()
